"""全局唯一的数据库连接池。V1_TASKS.md 第 2 步。

为什么要池:建连接的开销(TCP 握手 + 认证 + Postgres 服务端 fork 进程)
在一次性脚本里付一次无所谓,在每次提问都要付的服务里就是纯浪费。

四个必须做到的点(任务书 §4 第 2 步):
1. 池全局唯一 —— 所以它住在 core/,谁都从这里借,不各建各的。
2. register_vector() 在这里调 —— 它是**连接级**注册,不是全局的。
   每条物理连接都得注册一次,否则借到未注册的连接、传向量参数时会报错。
   (这是 PROJECT.md 6 节"集成必改三处"之外容易漏掉的第四处。)
3. @contextmanager 保证异常时连接也还得回去 —— 借了不还池子会空,系统会卡死。
4. maxconn=5 —— 池子不只是复用,也是限流:同时能有多少查询打到数据库,
   变成一个你能控制的数字。超过 5 个会排队,这是好事不是缺陷。
"""

from contextlib import contextmanager

from pgvector.psycopg2 import register_vector
from psycopg2.pool import SimpleConnectionPool

from app.core.config import DB_DSN

# 模块加载时创建一次,进程内全局唯一。
_pool = SimpleConnectionPool(minconn=1, maxconn=5, dsn=DB_DSN)

# 已经注册过 vector 类型的物理连接。池子最多 5 条,所以这个集合最多 5 个元素,
# 不会无限增长。用集合而不是"每次都 register" 是为了省掉每次借连接时
# 那一次查 vector 类型 OID 的往返。
_vector_registered: set[int] = set()

# HNSW 索引的迭代扫描。默认关闭,而关闭时 pgvector 是**后过滤**:先沿索引取
# ef_search(默认 40)个最近邻,再套 WHERE 条件。硬条件越挑剔,幸存的越少 ——
# 实测 property_type='apartment'(占全库 17%)+ limit=5 有的查询只返回 3 条,
# 有的直接返回 0 条,而库里明明有几千套。系统会因此对着存在的房源说"没找到",
# 这比返回得少更糟:它让"没找到"这个诚实信号变得不可信。
#
# 打开后 pgvector 会继续沿索引往下扫,直到凑够 limit 条满足 WHERE 的行。
# 实测(2026-09-07,20800 行):5 类挑剔条件 × 3 个查询,召回从 5~15/15 提升到
# 全部 15/15,与不走索引的精确扫描一致,延迟不变(中位数 1.67 ms,和有缺陷的
# 默认设置一模一样)。
#
# 为什么用 relaxed_order 而不是 strict_order:两者延迟相同,但 relaxed 与精确
# 扫描的结果吻合度略高(8/12 vs 7/12)。HNSW 本就是近似最近邻,不可能 12/12。
#
# 为什么这行放在这里,而不是紧贴查询放进 app/search/search.py:
# search.py 是 Member B 的跨线交付,V1_TASKS.md 第 3 步规定只改 4 处、SQL 与
# 函数签名一字不动。而 db.py 本来就是"让借出的连接能正确跑向量查询"的地方
# (register_vector 也在这儿,还是任务书点名要求放这儿的),这一行是同一类事。
# 已同步 Member B;若对方决定收进检索层,把这行删掉即可,调用方无感。
HNSW_ITERATIVE_SCAN = "relaxed_order"


@contextmanager
def get_connection():
    """从池借一条连接,用完自动还回。

        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")

    正常退出会 commit(即使只读,也要结束掉 psycopg2 自动开的那个事务,
    不然连接带着一个悬空事务回到池子里)。出异常则 rollback 后再还回去,
    下一个借到它的人拿到的一定是干净状态。
    """
    conn = _pool.getconn()
    try:
        if id(conn) not in _vector_registered:
            register_vector(conn)
            _vector_registered.add(id(conn))
        conn.cursor().execute(f"SET LOCAL hnsw.iterative_scan = {HNSW_ITERATIVE_SCAN}")
        yield conn
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()
    finally:
        _pool.putconn(conn)


def close_pool() -> None:
    """进程退出时把池里所有连接关掉。CLI 退出时调一次即可。"""
    _pool.closeall()
    _vector_registered.clear()

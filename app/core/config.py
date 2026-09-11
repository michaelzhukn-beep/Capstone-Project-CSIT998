"""集中读取配置。V1_TASKS.md 第 1 步。

规则:必需项缺失就在导入时抛异常,绝不静默用默认值。
配置不许猜,和 formulas.py「算不出来返回 None」是同一个道理的两个方向。
"""

import os

from dotenv import load_dotenv

# 从项目根目录的 .env 读进环境变量。已存在的真实环境变量优先(不覆盖),
# 这样 CI / 生产环境可以直接注入,不需要落一个 .env 文件。
load_dotenv()


def _required(name: str) -> str:
    """取一个必需的配置项,缺失或为空就立刻炸。"""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"缺少必需的配置项 {name}。"
            f"请复制 .env.example 为 .env 并填好 {name}(参考 V1_TASKS.md 第 1 步)。"
        )
    return value


def _optional(name: str) -> str | None:
    """取一个可选项。空字符串一律当没填,返回 None —— 不要让 "" 混进下游。"""
    return os.getenv(name) or None


# ---- 导入即校验:没有这两项,整个系统一步都走不了 ----
DB_DSN: str = _required("DB_DSN")
EMBED_MODEL: str = _required("EMBED_MODEL")

# ---- LLM 配置 ----
# 这三项故意不在导入时校验:第 2~5 步(连接池 / 检索 / 公式 / 估值)不需要 LLM,
# 没配 key 也应该能跑能测。校验推迟到真要建 LLM 客户端的那一刻,
# 由 require_llm_config() 负责 —— 仍然是"用之前就炸",没有静默默认值。
LLM_API_KEY: str | None = _optional("LLM_API_KEY")
LLM_MODEL: str | None = _optional("LLM_MODEL")
LLM_BASE_URL: str | None = _optional("LLM_BASE_URL")  # 留空 = OpenAI 官方地址


# ---- 投资测算假设(V2 第 4 项)----
# 数据集不含运营支出,所以 NOI / Cap Rate / ROI 建立在假设之上。
#
# 这里给默认值,和上面「必需项缺失就炸」不矛盾:DB_DSN 猜错了系统直接不能用,
# 而这些数是**行业惯例区间内的一个取值**,猜不猜得准是程度问题不是对错问题。
# 真正的红线是别的:**假设可以有,但必须明码标价。** 所以
#   1. 它们的值会随每一条计算结果一起往下传(见 analytics/assumptions.py),
#   2. 输出里每个基于假设的数字都带标注,
#   3. 用户可以在 .env 改,也可以在命令行里当场改。
# 被禁止的从来不是「使用假设」,而是「把假设当成数据端上来」。
#
# 注意:印花税**不在这里** —— 它是维州法定分档税率,有明确出处,可以精确
# 算出来,属于「法条」不属于「假设」,见 analytics/formulas.py 的
# stamp_duty_vic()。别把有出处的东西降格成假设。
def _rate(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} 必须是小数,例如 0.28,当前是 {raw!r}") from exc
    if not 0 <= value < 1:
        raise RuntimeError(f"{name} 必须在 [0, 1) 之间,当前是 {value}")
    return value


def _money(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = int(float(raw))
    except ValueError as exc:
        raise RuntimeError(f"{name} 必须是数字(澳元),例如 2000,当前是 {raw!r}") from exc
    if value < 0:
        raise RuntimeError(f"{name} 不能是负数,当前是 {value}")
    return value


# 运营支出占年租金的比例。物业管理费、市政费、保险、维修、空置损失等。
# 行业惯例区间 25%~30%,取中值。改这个值请在交付文档里同步改。
OPEX_RATE: float = _rate("OPEX_RATE", 0.28)

# 印花税之外的购置开销:过户/律师费、验房费等,单位澳元的固定金额。
# 之所以用固定金额而不是百分比:这些是服务费,不随房价等比缩放。
# ⚠️ 2000 是个粗略值,可按实际报价改。好在它量级很小 —— 一套 50 万的房子
# 印花税约 2.5 万,这 2000 只占总投入的 0.4%,对 ROI 的影响在小数点后第二位。
OTHER_ACQUISITION_COSTS: int = _money("OTHER_ACQUISITION_COSTS", 2_000)


def require_llm_config() -> tuple[str, str, str | None]:
    """要用 LLM 时调这个。缺 key 或 model 就抛异常,返回 (key, model, base_url)。"""
    if not LLM_API_KEY:
        raise RuntimeError("缺少必需的配置项 LLM_API_KEY —— 编排层需要它才能调 LLM。")
    if not LLM_MODEL:
        raise RuntimeError("缺少必需的配置项 LLM_MODEL —— 例如 gpt-4o-mini 或 deepseek-chat。")
    return LLM_API_KEY, LLM_MODEL, LLM_BASE_URL

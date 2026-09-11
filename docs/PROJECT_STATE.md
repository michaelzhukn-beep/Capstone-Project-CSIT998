# PROJECT_STATE

> 这份文件回答一个问题:**项目现在是什么状态。**
> 它不是开发日志。过期的内容直接替换掉,不要往后堆。
> 写入规则见 `AGENTS.md` §4。

最后更新:2026-09-11

---

## Goal

墨尔本找房助手(**筑明AI** / **Nestwise**),CSIT998 毕业项目。

用 LLM 编排真实数据回答自然语言找房需求。核心主张不是"能聊天",而是
**给出的每一个数字都能说清它从哪来** —— 实测/法定、基于可调假设、还是模型预测,
三类在措辞和视觉上都必须分得开。

## Current Working State

端到端可用。需要先起数据库(Docker,Postgres + pgvector,端口 15432),再跑
`python serve.py`(默认 8000)。

- 数据:20,800 条墨尔本成交记录 + OSM 地理快照 + 规划分区 + 学区 + LGA 罪案率
- 估值模型已训练并保存在 `models/`(XGBoost,对数价)
- 界面中英双语,右上角一个开关切换
- LLM 走 OpenAI 兼容端点(当前 DeepSeek),key 在 `.env`,**不入库**

## Completed Features

以下都是**已集成并实测可用**的。实验性内容见下面 Known Issues。

- **编排**:LangGraph 七节点 `parse_intent → search → analyze → enrich → rank →
  present → explain`,`MemorySaver` 记忆多轮
- **检索**:pgvector 语义检索 + SQL 硬条件
- **估值**:XGBoost 对数价模型,按房型给典型误差;派生特征 `is_unit_address`
- **周边与环境**:OSM 设施距离;注册表驱动的 15 个抽象属性(安静/热闹/便利…),
  分位数打分 + 全库排位(`score_rank`)
- **事实层**:学区归属、规划分区与叠加层、LGA 罪案率
- **网页界面**:对话流 + 可编辑条件卡 + 房源卡 + 常驻 Leaflet 地图 + 可拖拽详情窗 +
  换一批
- **详情窗五段**:价格区间 / 区位与环境 / 购置成本 / 出租测算 / 学区规划治安
- **就地试算**:详情窗里两个假设可直接改,`/api/recalc` 用同一份公式即时重算
- **距离测算**:`/api/measure` 解析地名并量直线距离,地图上画图钉 + 连线 + 读数
- **中英双语**:前端文案表 + `/api/meta?lang=`,`lang` 贯穿 chat/refine/rebatch
- **对外分享**:`share.py` / `share-web.bat`,起服务 + Cloudflare Quick Tunnel

## Current Task

无。共享协作机制已由 Codex 核查并补强,规则统一保存在 `AGENTS.md`。
本次验证范围为六份共享文件、核心代码静态核对、Git 状态/diff/两条提交历史及
当前容器端口;未重跑业务测试或端到端验收,未修改业务代码。

下一件该做的事见 `TODO.md` 的 **Now**。

## Recent Changes

只保留仍然影响判断的那几条。

- 跨 Agent 共享记忆已接入:`AGENTS.md` 明确新会话/上下文恢复、未跟踪文件检查、
  自动交接与验证边界;`CLAUDE.md` 引用同一协议,不另存一套规则
- 品牌改为 筑明AI / Nestwise;首屏改成飘动的示例词条
- 距离测算功能上线,替换掉详情窗里意义不大的 `near_place` 那一格
- 两个假设从窗口底部搬到它们各自影响的那一行旁边,可就地编辑
- 中英双语开关上线
- 修掉「426 行脏数据」的误判:数据没问题,是中文标签译错了(详见 NOTES V9.4)

## Known Issues

- **仓库几乎没有提交历史。** `git log` 只有 2 条旧提交,`app/`、`tests/`、
  `docs/`、`AGENTS.md`、`CLAUDE.md` 及部分新增 `pipeline/` 脚本仍是 untracked
  (早期 pipeline 脚本已跟踪)。普通 `git diff` 不包含未跟踪文件;本地交接须直接
  阅读它们,新克隆也不会取得这些代码和协作规则。基线提交仍待完成,见 TODO Now。
- **数据库启动配置不一致。** 当前 `capstone_postgres` 容器映射 `15432 → 5432`,
  但 `db/docker-compose.yml` 仍为 `5432:5432`(与现有提交一致)。当前运行配置的
  来源尚未确认;重建容器前须核对端口与 `DB_DSN`,本次仅记录差异,未修改配置。
- `tests/test_api.py` 偶发失败(批量连跑时约 1/24,曾表现为 rc=139 段错误),
  单独重跑无法复现。用 `PYTHONFAULTHANDLER=1` 捕获。
- **未做:与纯 LLM 对比的幻觉率评估。** 提案里承诺过,前提已经具备。
- `_rhine_analysis/`(约 9MB,3D + 音频 + 抓取脚本)**与本项目无关**,疑似其他任务
  遗留在此。删除前请先与所有者确认。
- `redesign/` 是空目录。
- **品牌冲突**:`qisuo-redesign/mockup.html` 用的是「栖所 QISUO」,而线上已定名
  筑明AI / Nestwise。那份 mockup 是更早的探索,**不要照它改界面**。
- 假设是**进程级**的:一个人改了所有人都变。单机演示没问题,多人同时用需要把它
  挪进会话状态。
- 会话存在内存里(`MemorySaver`),重启服务即丢失。
- `README.md` 正文仍是 Member B 早期的「数据 + 检索」那一版,把 `search.py` 说成
  交付物 —— 助手本体现在在 `app/`。顶部已加指引,但正文尚未重写。

## Next Steps

1. 补一次基线提交,让 git 历史真正可用(见 TODO Now)
2. 幻觉率评估(`eval/run_eval.py`,要 LLM,约 20 分钟)
3. 用户明确延后的两项:电车噪音源、顶栏「假设」按钮改名 + 中英文标点统一

## Important Constraints

改动涉及以下任何一条时,先读 `docs/DECISIONS.md`。

- **三类数字必须可分辨**:实测/法定、基于假设、模型预测。这是项目的中心主张。
- **不许编造房源或数字。** 没结果时那条路径**故意不过 LLM**。
- **所有距离都是直线距离。** 没有路网数据,步行/驾车时间必须如实说答不了。
- **不要为了"修数据"去改数据集** —— 组员会重新下载覆盖。要改就改标签、特征或展示。
- 界面上**决定"看不看得见"的属性,不许依赖动画或过渡**。
- `.env` 里有真实 LLM key,已 gitignore,保持如此。
- `data/` 大部分不入库,可由 `pipeline/` 脚本重建,顺序见 `README.md` 与
  `NOTES_FOR_SUPERVISOR.md` 的「如何重建全部数据」。

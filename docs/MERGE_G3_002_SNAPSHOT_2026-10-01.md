# G3-002 本轮假设描述：独立审核、主项目合入与停工

完成时间 UTC：2026-10-01T07:03:54.417663+00:00。G3-002 已修；本轮开发、测试结束，G3-001/002 完成后暂停，不启动新测试或方向。当前总清单见 CURRENT_ISSUES_2026-10-01.md。

## 问题与最小修复

轮中进程级假设由28.4%/$2,000改为40%/$5,000时，指标仍用本轮快照，但 SSE done.assumptions 原来描述后来全局值。当前前端不消费这一字段；修复的是 API 描述与指标的对应关系，不宣称发现页面显示40%的症状。

按冻结的 G3-002_server.diff 三个 hunk 核对上下文合入 app/api/server.py，并作有限审查修正：
- 按有效 state.assumption_snap.display → 第一条 metrics.assumptions → 当前全局快照选择来源；旧状态、无数字状态维持兼容。数值验证排除缺字段、bool、字符串、NaN/Infinity，保留候选的有限数值契约，不宣称检查任意损坏状态。
- 后端不再读取私有 assumptions._SPEC；仅检查该API所用的两个公开字段。中文格式器委托 assumptions.describe(snap)。
- app/analytics/assumptions.py 的原 describe 添加可选快照。文案仍在原模块单处维护，合法默认调用输出不变；货币按 set_rate 的整数金额契约格式化。格式化不设置、重置或修改全局值。无本轮快照时也只格式化一次捕获的当前快照。
- 原 refinement/rebatch入口、图编排、公式、回滚、锁、路由、认证、前端、ROI和车位逻辑均保留。未复制累计候选文件覆盖，未改变真实数据。

## 主源码验证

- 后端原51项断言全部通过：轮中漂移且全局保留新值、正常轮、旧状态只有metrics、无快照/无指标、values=None、六种坏快照退回有效metrics、refinement准备的7个键、后续轮/分页字段、错误不发done、错误回滚含旧快照/history、回滚失败标志、忙会话错误、done的7个字段。
- 无漂移事件的归一化摘要与修复前基线一致；原有定义中只改_run，新增四个小助手。assumptions模块只改describe格式入口。
- Chrome Chrome/154.0.8037.92 实际主前端、双语114/114通过（写前112/114）；G3-001的82项仍通过。记录12条被阻断CDN的资源错误，与基线一致。
- G3-001主源码精度30/30及文案65/65通过。主源码两文件语法在暂存阶段由compile检查，未运行FastAPI导入或lifespan。
- 复用原测试；独立副本仅改输入/输出/冻结基线位置、无头浏览器独立端口/profile和隐藏启动方式，51/114断言不改。主回归使用合入后的实际server和assumptions。
- 全部为两个合成房源、假graph/LLM、真实formulas与AST提取的_run，模拟轮中漂移。不是实际HTTP并发、真实图节点、真实LLM、模型或完整生产E2E；未读.env、写真实DB、迁移、重训、付费调用、提交、推送或部署。

## 证据与保留

D:/projects/capstone-audit-20261001-g3-002：
baseline/ 为写前源码/状态；stable_candidate.diff 为原候选；server.py.diff、assumptions.py.diff 为实际最小差异；manifest.json 为源码哈希与保护结果。
backend/main_backend.json、logs/main_backend.log 是主源码51项；browser/main_after.json、logs/main_browser.log 是实际主前端114项；logs/main_opex_precision.log、main_i18n.log 是相关回归。
复跑说明留作证据，当前已暂停，勿自动再跑：
python -B D:/projects/capstone-audit-20261001-g3-002/scripts/main_backend.py candidate
其中 candidate 仅为沿用原脚本的差异断言模式；SERVER 固定为主项目，比较源码固定为写前备份，不是运行隔离产品。

| 源码 | 写前 SHA256 | 写后 SHA256 |
|---|---|---|
| server.py | D4B01A753EBB6F642196D6FC42DBB6CADEE2A6C08CAC37EE9916A486EB0E1FDE | 0295C359F6E9C748CDB4EBD0A84B00F1DA62E7E59F4041EA61508E2559B18597 |
| assumptions.py | BB30B7E5E3D68CCABE59A4A111FF332BD666D15BBC077BEEF940094E60B00ED9 | A6B1C38D9A8C84C9A97FB56182EF463AB4DA5FB80A086AB5F5CA02C07BB1A06B |

G3-001 app.js 的 CE61CBD7F8B3AEFE259AE8ED1DE1AC6FA86DFFA3DF4F10ACF7C85692E9AE2FC0 及其他受保护ROI/车位/认证源码未改；全部原dirty条目保留，最终统计在manifest。记录文件为本轮新增或最小更新，历史审计保留其当时结论。

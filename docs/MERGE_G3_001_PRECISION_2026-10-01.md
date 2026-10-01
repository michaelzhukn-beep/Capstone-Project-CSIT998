# G3-001 百分比显示精度：独立审查与选择性合入

2026-10-01。结论：G3-001 已合入并通过定向回归；G3-002 未在本次修复。两项修复完成后暂停，不扩展新测试。

## 现象、根因与修复

详情出租测算用本轮假设 0.284 计算 NOI/ROI，运营支出输入框却经 Math.round 显示 28%，和计算依据不一致；靠近 1 的合法比例甚至显示 100%。

仅按稳定差异的一处 hunk 替换主项目 app/web/app.js 的输入框初始化：
- 将 JSON 解析后的双精度数的最短往返十进制文本小数点右移两位，不做浮点乘法或取整：0.284 → 28.4，1e-7 → 0.00001，0.9999999999999999 → 99.99999999999999。
- step=any、min=0、max=99.99999999999999 与原 change 处理的 0 ≤ v < 100 一致。输入 100 无效且不发重算；输入合法极端值有效并发送 <1 的比例。
- 快照来源 m.assumptions、live 值、编辑除以 100、计算公式、ROI/车位/认证后端均未改。只修正候选的一行注释：保证解析后数值的十进制文本，不声称保留原始 JSON 字符串或任意精度。
- 新增 tests/test_opex_display_precision.mjs，沿用原有 30 个检查，只调整主项目默认路径与使用说明。

## 核验结果与边界

主项目 Node 语法通过；精度 30/30、原数值格式 35/35、文案组合 65/65、车位 UI 11/11 通过。

主项目真实前端、Chrome Chrome/154.0.8037.92、中英合成数据浏览器检查 112/114：
- G3-001 的 82 项全部通过；修复前失败 38 项，原先通过而本次失败 0 项。
- 覆盖合法 0、正常小数、微小比例、接近 100% 的值、输入 100 拒绝、合法极端值接受、编辑 30.5→0.305、NOI 与实际公式对应、轮中/轮后全局变化不影响详情本轮值。
- 直接对 null、NaN、±Infinity、-0.2、-1e-7 调用格式函数，再交给真实 Chrome number input，均不产生可由原处理接受的比例；无异常值伪装为有效 0%。这些是超出假设输入契约的观察，不证明真实 payload 可达。
- 剩余两项为 G3-002：轮中将全局假设改为 40%/$5,000 后，server._run 的 done.assumptions 描述全局值，而 metrics 仍是本轮 28.4%/$2,000。前端当前不读取 done.assumptions，未发现这两项的页面显示影响。后端最小修复由协调任务继续。
- 浏览器记录 12 条被阻断 CDN 的资源错误，与原夹具一致。外部资源加载效果、真实 DB/数据/模型/LLM 和完整生产路径不在验证范围；使用两个合成房源、模拟 API/graph/LLM，真实 formulas 与 AST 提取的 server._run。没有读 .env、真实数据库写入或付费调用。

## 精确证据

主文件 SHA256：
- 写前 C85DC11AFAD603C403C4CA0DAD8AB9A3D124540A16CCC1A615CBE938ECB3DD87
- 写后 CE61CBD7F8B3AEFE259AE8ED1DE1AC6FA86DFFA3DF4F10ACF7C85692E9AE2FC0
稳定候选 SHA256：A243EB41892F6F2FA36BA36D980F555E26274C58CFE64E14C19ADE436FE4E6E5。实际主文件差异还含上述一行准确性注释修正。
回归脚本 SHA256：C66B964201121D8B57294CB6D89D20C30CAE23A899D6BFC6107DB439C37C0092。

独立证据目录：D:\projects\capstone-audit-20261001-g3-001
- baseline/app.js、baseline/git_status.txt：写前工作树备份与原有 82 项 dirty 记录。
- stable_candidate.diff、applied_app.diff、manifest.json：稳定补丁、实际单 hunk 差异、受保护源码 hash 与核验结果。
- logs/main_precision.log、main_number_format.log、main_i18n_semantics.log、main_parking_visibility.log：主源码回归。
- browser/main_after.json、logs/main_browser.log：114 项原浏览器检查及 6 项异常输入观察。独立浏览器驱动只调整输出目录/端口/profile、隐藏启动窗口，并加入上述异常观察；未覆盖协调线程原证据。
- 合入时逐项断言基线及 hunk 上下文，保留原工作树所有条目；未拷贝累计候选 app.js，未带入其他 ROI 补丁。

待办仅 G3-002 最小修复审核；本次未启动新的问题调查。

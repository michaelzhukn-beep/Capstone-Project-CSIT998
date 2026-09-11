# TODO

> 当前工作队列。状态必须和代码一致:做完了就移走,没做就不许标 Done。
> 写入规则见 `AGENTS.md` §4。

最后更新:2026-09-11

---

## Now

- [ ] **决定基线提交要不要 push。** 本地已提交 `e382140`(97 文件)。
      卡点:`data/planning.jsonl.gz` 71MB,过 GitHub 50MB 警告线,推上去就进历史,
      移除要改写历史。选项:照推 / 改用 Git LFS / 把它移出白名单由脚本重建。
- [ ] **清理 Docker 容器归属。** 现在 `docker compose up -d` 会重建那个已退出的
      `capstone_postgres_old5432` 当 `db`,并把在跑的手工容器改名让路,两者争 15432。
      要做的是:停掉并删除这两个容器,用 compose 重新拉起(卷 `capstone_pgdata`
      共用,不丢数据),再验证 `python serve.py` 能连上。

## Next

- [ ] `app/api/server.py:102` 启动打印 `R²`,GBK 控制台下抛 `UnicodeEncodeError`
      打死 lifespan(组员用 cmd 会踩)。让启动输出对非 UTF-8 终端安全。
- [ ] `search.py` 与 `pipeline/load_properties.py` 的 DSN 仍是硬编码(端口已跟进到
      15432)。改成从 `app.core.config` 读,消掉这两处副本。
- [ ] **幻觉率评估:本系统 vs 纯 LLM。** 提案里承诺过,不能砍。前提已具备:
      `python -m eval.run_eval`(要 LLM,约 20 分钟);`--report` 可只重出报告。
- [ ] `tests/test_api.py` 偶发失败定位(批量连跑约 1/24)。
      复现手段:`PYTHONFAULTHANDLER=1` 连跑整套若干轮。

## Later

- [ ] 电车噪音源纳入「安静」评分(外部反馈第 5 项,所有者明确延后)
- [ ] 顶栏「假设」按钮改名 + 全站中英文标点统一(外部反馈第 6 项,所有者明确延后)
- [ ] 假设从进程级挪进会话状态(多人同时使用才需要)
- [ ] `MemorySaver` 换成 `SqliteSaver`,让会话跨重启存活(图本身不用改)
- [ ] 决定 `_rhine_analysis/` 的去留(与本项目无关,约 9MB;删除前需所有者确认)
- [ ] 重写 `README.md` 正文:它仍停在 Member B 的数据/检索那一版,
      把 `search.py` 说成交付物,没提 `app/`

## Done

只保留最近、仍有参考价值的。更早的完整记录在 `NOTES_FOR_SUPERVISOR.md`。

- [x] 基线提交(本地 `e382140`):助手本体 `app/`、`tests/`、`docs/`、`eval/`、
      协作规则与数据快照入库;`_rhine_analysis/` 排除在外并加进 `.gitignore`。**未 push**
- [x] 统一数据库端口:compose 改 `15432:5432`,README / `.env.example` /
      两个硬编码脚本跟进。差异来源已查明 —— 在跑的容器是手工 `docker run` 起的

- [x] 接入并由 Codex 核查共享记忆机制:统一 `AGENTS.md`、新会话恢复与自动交接;
      已核对代码/Git/文档,本次未重跑业务验收
- [x] 品牌改名 筑明AI / Nestwise;首屏改成随机浮动的示例词条(八条全部验证过可解析)
- [x] 距离测算(`/api/measure` + 地图连线读数),替换掉详情窗里的 `near_place` 格
- [x] 假设改为就地可编辑(`/api/recalc`),拆掉窗口底部那个假设框
- [x] 中英双语一键切换(`/api/meta?lang=` + `app/i18n.py` + `app/web/i18n.js`)
- [x] 详情窗按「买房人会问的问题」重排为五段,措辞从口语收回书面
- [x] 估值模型加派生特征 `is_unit_address`(MAE 149,365 → 147,642)

# TODO

> 当前工作队列。状态必须和代码一致:做完了就移走,没做就不许标 Done。
> 写入规则见 `AGENTS.md` §4。

最后更新:2026-09-11

---

## Now

- [ ] **补一次基线提交。** `app/`、`tests/`、`docs/`、`AGENTS.md`、`CLAUDE.md`
      及部分新增 `pipeline/` 脚本仍是 untracked,`git log` 只有 2 条旧提交。
      普通 diff 看不到这些文件,新克隆也拿不到共享规则;须一并纳入基线。
      需要所有者确认后再提交(`.env` 已 gitignore,确认 `data/` 的白名单规则符合预期)。

## Next

- [ ] 核对并统一数据库启动配置:当前容器暴露 15432,仓库 Compose 映射 5432;
      查明差异来源并核对 `DB_DSN`,再验证文档中的重建步骤。
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

- [x] 接入并由 Codex 核查共享记忆机制:统一 `AGENTS.md`、新会话恢复与自动交接;
      已核对代码/Git/文档,本次未重跑业务验收
- [x] 品牌改名 筑明AI / Nestwise;首屏改成随机浮动的示例词条(八条全部验证过可解析)
- [x] 距离测算(`/api/measure` + 地图连线读数),替换掉详情窗里的 `near_place` 格
- [x] 假设改为就地可编辑(`/api/recalc`),拆掉窗口底部那个假设框
- [x] 中英双语一键切换(`/api/meta?lang=` + `app/i18n.py` + `app/web/i18n.js`)
- [x] 详情窗按「买房人会问的问题」重排为五段,措辞从口语收回书面
- [x] 估值模型加派生特征 `is_unit_address`(MAE 149,365 → 147,642)

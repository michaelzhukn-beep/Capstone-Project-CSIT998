# CLAUDE.md

@AGENTS.md

## Claude-specific instructions

1. **Follow `AGENTS.md` above.** It is the shared protocol with Codex and is authoritative.
   Do not restate or fork those rules here.
2. **On entering this project — or whenever context feels uncertain, compacted, or
   second-hand — recover state from `docs/PROJECT_STATE.md`, `docs/TODO.md`, the actual
   code and Git.** Never from remembered conversation. If this session's memory and the
   repository disagree, the repository is right.
3. **After any meaningful task, run the Agent Handoff Check (`AGENTS.md` §3) before
   reporting completion**, and end with the `Shared state updated:` block. Respect the
   **update cadence** in that section: run the check every time, but only *write* the
   documents when the owner asks (「更新」 / hand over / wrap up). Otherwise close with a
   one-line `待更新:…`. The single exception is a newly found unresolved bug — record
   that immediately, in one line.
4. **If you find changes Codex left behind, understand them before continuing.** Never
   overwrite another agent's valid work to restore a state you remember. If Codex's
   wording conflicts with an owner instruction, the owner wins — but encode the
   resolution in `AGENTS.md` / `docs/DECISIONS.md` instead of silently reverting.

A `SessionStart` hook (`.claude/settings.json` → `.claude/session_brief.py`) prints a
short brief on entering the project and after a compaction: where shared memory lives,
whether the docs currently lag the code, and the top of `TODO.md`'s **Now**. It is
read-only, project-scoped, gitignored, and never fails the session. Rerun it by hand with
`python .claude/session_brief.py`.

The rest of this file is operational detail for running the project from Claude Code.

---

## Running it

Postgres + pgvector must be up first. Both the local container and the checked-in
Compose file now use **15432:5432**. Container ownership is still unresolved: the
running container was started manually, while Compose owns an exited older one.
**Do not run the command below until that conflict is resolved**; follow
`docs/PROJECT_STATE.md` Known Issues and `docs/TODO.md` Now first:

```bash
docker compose -f db/docker-compose.yml up -d
```

Then:

```bash
python serve.py                 # http://localhost:8000
python serve.py --port=8900     # 8900 is what .claude/launch.json uses (8520 and later 8600 fell into excluded ranges, 2026-09-30 / 2026-10-05)
python share.py                 # server + Cloudflare tunnel, prints a public URL
```

If a port refuses to bind for no apparent reason, it is probably inside a Windows
excluded range. Those ranges are assigned dynamically (Hyper-V/WSL) and **change across
reboots**, so check, don't memorise:

```bash
netsh interface ipv4 show excludedportrange protocol=tcp
```

`.py` changes need a server restart. `.js` / `.css` / `.html` changes only need a page
refresh — static files are served with `Cache-Control: no-cache`.

## Tests

Plain scripts, no pytest. All eight must pass before reporting a task done:

```bash
for f in tests/test_*.py; do python "$f"; done
```

`tests/test_api.py` fails intermittently (~1 in 24) during batch runs and has not been
reproduced in isolation — see Known Issues. Re-run it alone before assuming a real break.

## Verifying UI work in the Browser pane

Use the Browser pane against a preview server, not a hand-wave. Two environment
limitations are real and have cost hours; both are documented in `docs/DECISIONS.md`:

- **The animation clock does not advance in the pane.** CSS animations *and* transitions
  sit frozen at `currentTime: 0`. Anything whose visibility depends on an animation or
  transition completing will appear broken here and fine in a real browser — so never
  make visibility depend on one.
- **The map cannot zoom in the pane** (Leaflet's zoom animation is rAF-driven). Zoom
  behaviour has to be verified by the user in a real browser.
- **WebGL in the pane is not reliable.** On 2026-09-24 it had none (`webgl`/`webgl2` both null,
  so the homepage showroom fell back to SVG); on 2026-09-30 `webgl2` worked and the showroom
  rendered. Check `document.createElement('canvas').getContext('webgl2')` before trusting what
  the pane shows. If it is null, verify the showroom with headless GPU Chrome over CDP
  (`--headless=new --use-angle=d3d11 --ignore-gpu-blocklist`, then `Page.captureScreenshot`)
  or ask the owner to look.

Synthetic clicks and typing are also unreliable in the pane. `form_input` plus
`requestSubmit()` works; `computer` typing often silently does nothing.

## Things to leave alone

- `_ui-lab/` — a **separate, experimental** alternative frontend by another agent. It
  proxies `/api/*` to the main server and deliberately does not touch `app/`. Not the
  shipping UI. Do not merge it into `app/web/` without being asked.
- `_rhine_analysis/` — unrelated to this project (see PROJECT_STATE Known Issues).
- `design/`, `qisuo-redesign/` — design explorations, not live code.

# AGENTS.md — shared development protocol

This repository is worked on by **more than one AI agent** (Claude Code, Codex) plus the
human owner. This file is the **single source of truth for how agents hand work over to
each other**. Both agents follow this same file. `CLAUDE.md` imports it and only adds
Claude-specific operational notes; it does not restate these rules.

---

## 0. The one rule everything else follows

**Chat history is not shared memory.**

Codex cannot see Claude Code's conversation. Claude Code cannot see Codex's conversation.
A conversation is scratch space for one agent in one session. Anything the next agent
needs must exist in the repository.

Cross-agent memory is these six repository sources, in this priority order:

| # | Source of truth | Why it ranks here |
|---|---|---|
| 1 | **The actual code** | It is what runs. It cannot be out of date with itself. |
| 2 | **`git status` / `git diff` / recent commits** | Shows what changed and what is still in flight. |
| 3 | **`docs/PROJECT_STATE.md`** | Where the project stands right now. |
| 4 | **`docs/TODO.md`** | The work queue. |
| 5 | **`docs/ARCHITECTURE.md`** | How it works. |
| 6 | **`docs/DECISIONS.md`** | Why it was built that way. |

Chat history is temporary session context, not a shared-memory source. Put any
handoff-critical information in the repository before ending the task.

When a document disagrees with the code, **the code wins** — but do not just silently
patch the doc. Read the code and the git history first, work out *why* it diverged, then
correct the document. A divergence is usually information, not noise.

---

## 1. Before meaningful work

These rules apply to both Claude Code and Codex in every new session. On entry, or
after context loss/compaction, recover state from this file and the sources below.
Do this before meaningful development, including changes to the shared workflow.
Skip the full check for a one-line typo fix.

1. Read `docs/PROJECT_STATE.md` — goal, current state, done, in flight, known issues, next.
2. Read `docs/TODO.md` — do not rebuild something already in **Done**.
3. If the task touches architecture (API, data flow, LLM/orchestration, search, map,
   valuation, database, frontend structure, directory layout), read `docs/ARCHITECTURE.md`.
4. If the task might affect an existing design choice, read `docs/DECISIONS.md` **first**.
   Do not overturn a recorded decision without knowing why it was made.
5. **Read the relevant code.** The docs restore context; they are not a substitute for
   reading the implementation you are about to change.
6. Check `git status` before editing; inspect relevant `git diff` (including staged
   changes) and recent commits when recovering context or anything looks unfamiliar.
   Untracked files do not appear in ordinary `git diff`; read relevant ones directly.

## 2. Recognising the other agent's work

If you find code, docs, files or TODO entries that your own session did not produce,
**assume they are valid work by another agent.**

Understand them before acting: what changed, why, is it finished, is it related to your
task, is anything left half-done.

**Never revert another agent's work just to restore the state you remember.**
Your memory of this repository is not evidence.
This includes overwriting or deleting unfamiliar uncommitted and untracked work.

## 3. After meaningful work — Agent Handoff Check

Before telling the user any meaningful task is done, **run this check — every time.**
Reading it is cheap. What you do with the result follows the cadence rule below.
When you do write, update only the files the work actually affected — not all four.

1. If Claude/Codex were closed right now, could the other agent take over using only
   code + git + `docs/`?
2. Is `docs/PROJECT_STATE.md` still accurate?
3. Is `docs/TODO.md` still accurate?
4. Did the architecture change? If so, is `docs/ARCHITECTURE.md` updated?
5. Was a long-lived design decision made? If so, is `docs/DECISIONS.md` updated?
6. Did this work uncover a problem that is still unsolved? Is it in **Known Issues** / TODO?
7. Are planned, experimental and unfinished items clearly labelled, rather than
   recorded as completed features?
8. Have completed tasks been removed from Now/Next (or moved to recent Done)?
9. Would the next agent know what was just completed and what comes next?

### Update cadence — the owner's policy

The owner has asked that the documents **not** be rewritten after every small change:
a one-line fix must not cost a documentation pass.

- **Run the check every time.** It is reading, not writing.
- **Write the documents when the owner asks** — the word 「更新」, or any request to hand
  over / wrap up / switch agents. Then do the full pass across every affected file.
- **Between those points, do not rewrite the docs.** Close the task with one line naming
  what is outstanding instead, e.g.
  `待更新:PROJECT_STATE(距离测算已上线)· TODO(Now 第 1 项完成)`.
  The next 「更新」 turns those lines into edits.
- **One standing exception, always immediate:** a newly discovered *unresolved* problem
  goes into Known Issues (or TODO) at once, one line. A deferred doc update is
  recoverable; a forgotten bug is not.

This cadence is the owner's decision and outranks any agent's preference. **Do not
"correct" it back to updating automatically.** See `docs/DECISIONS.md`.

Any failed applicable check → fix the affected file before reporting completion,
subject to the cadence above.
Keep the validation performed, its outcome, and any unverified work or blockers
with the current task state, briefly enough for the next agent to resume. Do not
claim completion when required work remains; preserve its `in progress` status.

End the final response with this standalone block. `yes` means the file was updated
in this task; `no` means it was reviewed and needed no change, not that the check failed.
If the cadence rule deferred a write, add a `Pending:` line naming what is waiting:

```
Shared state updated:
- PROJECT_STATE: yes/no
- TODO: yes/no
- ARCHITECTURE: yes/no
- DECISIONS: yes/no
```

## 4. What goes in which file

| File | Contains | Does **not** contain |
|---|---|---|
| `docs/PROJECT_STATE.md` | Goal, current working state, completed features, current task, recent changes, known issues, next steps, constraints | A development log. History. Anything superseded. |
| `docs/TODO.md` | `Now` / `Next` / `Later` / `Done` (recent only) | Finished work left marked unfinished, or planned work marked done |
| `docs/ARCHITECTURE.md` | How the system **actually works today**: modules, data flow, API surface, responsibilities | Aspirational designs, unless explicitly marked `planned` |
| `docs/DECISIONS.md` | Decisions that constrain future work, as Context / Decision / Reason / Consequences | A changelog. Ordinary code changes. |

### Update triggers

- **PROJECT_STATE** — a feature became usable; the current task ended; a new problem
  appeared or an old one was fixed; the next step changed.
- **TODO** — any task changed state. Both directions.
- **ARCHITECTURE** — a module was added or removed; the API surface changed; data flow
  changed; frontend/backend responsibilities moved; the LLM call flow changed; the data
  model changed; a directory took on a new job.
  *Not* for CSS, copy edits, small bug fixes, parameter tuning, or UI changes that leave
  the structure intact.
- **DECISIONS** — an approach was chosen over a viable alternative; something was ruled
  out and should stay ruled out; a constraint was established that a future agent would
  otherwise question.

## 5. Discussed ≠ decided ≠ done

Keep these apart in writing:

- discussed ≠ adopted
- planned ≠ in progress
- in progress ≠ complete
- experiment worked ≠ integrated
- code exists ≠ feature works
- some tests pass ≠ feature is finished

Only work that is **integrated and confirmed working** goes into Completed Features / Done.
Anything else is tagged `experimental` or `in progress` in the same line where it appears.

## 6. Shared docs are not chat summaries

Do not write "the user said…", "Claude suggested…", "Codex thought…", "we discussed…".

Write project facts: what the system is, what state it is in, how it is built, what was
decided. If a discussion produced a real decision, record the decision in `DECISIONS.md`
— not the discussion.

> Bad: "Claude and the user thought 3D might look better."
> Good: "Property cards use the 3D presentation." + a DECISIONS entry with the reason.

## 7. Keep the documents small

These files must stay readable years from now. Maintain them; do not append forever.

- PROJECT_STATE: replace stale state, do not accumulate it. Recent Changes keeps only
  what still matters.
- TODO: delete finished trivia; keep Done short and recent.
- Known Issues: delete once fixed.
- ARCHITECTURE: always describes today.
- DECISIONS: long entries are fine and are meant to survive — that is the one file that
  grows, because "why" stays useful.

If a file starts feeling like a diary, it is already wrong.

---

## 8. Conventions in this repository

- **Language.** `AGENTS.md` and `CLAUDE.md` are English (machine-facing protocol).
  `docs/*` and the long-form engineering record are **Chinese**, matching the rest of the
  repo and its code comments. Keep structural headings (`Now`, `Done`, `Completed
  Features`, …) in English so they stay greppable.
- **`NOTES_FOR_SUPERVISOR.md` is the long-form archive**, written for the human supervisor:
  full rationale, measurements, dead ends. `docs/DECISIONS.md` is the short index into it —
  each entry links to its NOTES section instead of copying it. **Do not duplicate NOTES
  content into `docs/`.**
- **`GAP_ANALYSIS.md`** records what was evaluated and deliberately excluded. Check it
  before proposing a "missing" feature; it may already have been ruled out with data.
- Tests live in `tests/` and are plain scripts: `python tests/test_x.py`, no pytest.
- Never commit `.env` (it holds a live LLM API key) — it is gitignored; keep it that way.

## 9. Non-negotiable product constraints

These are enforced in code and must not be weakened without a DECISIONS entry:

1. **Every number shown to the user is labelled by origin**: measured/statutory,
   assumption-based, or model-predicted. This is the project's central claim.
2. **No fabricated listings or numbers.** The no-result path deliberately bypasses the LLM.
3. **All distances are straight-line.** There is no road network; walking/driving time
   cannot be answered and must be reported as unsupported.
4. **Do not modify the dataset** to fix data problems — a teammate re-downloads it. Fix
   labels, features or presentation instead.

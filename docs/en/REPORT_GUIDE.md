# Final Report Revision Guide

For team members revising the A3 final report (due 18 October 2026, 11:55 pm) and preparing the
A4 presentation. It tells you which part of the report your area covers, which code and documents
to check it against, and what has already been decided.

## Where the report is

- The working copy is **Final Report v1.3 (Word)** in the group's shared OneDrive folder.
- The report is **not in this repository on purpose**: it contains student numbers, and this
  repository is public. Do not commit the report to Git.
- The final submission must be LaTeX in the proposal's template (12 pt, single spacing, at least
  30 pages). The Word copy already uses the same layout, so its page count (34) is a fair estimate.
  The content will be converted to LaTeX once all areas are finished.

## Rules for editing

1. Edit only the sections of your own area. If you find a problem elsewhere, tell its owner.
2. Turn on **Track Changes** in Word so the group leader can review every edit.
3. Do not change a number without checking its source in the code, `eval/results/`, or
   `NOTES_FOR_SUPERVISOR.md`.
4. Keep the terms as they are: *required / preferred*, *measured / assumption-based /
   model-predicted*, *straight-line distance*.
5. Do not add back content that v1.3 removed, and do not revert the corrections listed below.
6. Keep your section's length roughly the same. The whole report should stay at 32–34 pages
   after everyone's additions.

## Areas, report sections and what to check

These areas are also each member's responsibility in the final presentation and Q&A.

| Area | Report sections | Check against |
|---|---|---|
| **Backend and AI orchestration** | Ch. 3 System Architecture and AI Orchestration; Ch. 4 Trustworthy Numbers and Hallucination Prevention | `app/orchestration/graph.py` (the seven nodes; `parse_intent`, including the first-turn re-parse; `rank`; the no-result template), `app/orchestration/refinement.py` (multi-turn changes; relative goals use the median of the results just shown), `app/orchestration/answer_guard.py` (explanation checks), `app/analytics/formulas.py` (stamp duty, yield, NOI, ROI), `app/api/server.py` (`/api/recalc`, streaming) |
| **Retrieval and valuation model** | Sections 5.4–5.9 | `app/search/search.py`, ranking and ROI pool expansion in `app/orchestration/graph.py`, `app/amenities/zones.py` (school zones), `app/analytics/train_valuation.py`, `calibrate_valuation.py` (500 random half-splits per type), `crossfit_valuation.py`, `valuation.py`, `models/valuation_meta.json` |
| **Data** | Sections 5.1–5.3 | `pipeline/load_properties.py`, `pipeline/join_annual_rent.py` and `aggregate_rent_benchmarks.py` (rent tiers), `pipeline/fetch_osm.py`, `fetch_school_zones.py`, `fetch_planning.py`, `fetch_crime_stats.py`, `app/amenities/registry.py` (how "quiet", "lively" and the other qualities are built from map evidence), `app/amenities/context.py` (scores and percentile ranks), `GAP_ANALYSIS.md` |
| **Frontend and interface** | Ch. 6 Frontend Implementation | `app/web/index.html`, `app.js`, `app.css`, `i18n.js`, `map-glass.js`, `app/web/showroom/`, `docs/en/FEATURES.md` |
| **Testing and evaluation** | Ch. 2 Related Work and Research Gap; Ch. 7 Evaluation | `eval/questions.py`, `eval/run_eval.py`, `eval/results/answers.json` (the raw answers of every arm), `tests/`, and the competitor findings below. Note that `eval/results/report.md` still mixes in numbers from the earlier 20-question run; quote the report's Table 10, not that file. |
| **Project management and overall** | Abstract, Ch. 1, Ch. 8, Ch. 9, appendices | `docs/PROJECT_STATE.md`, `docs/DECISIONS.md`, `git log` (dates for Table 13), `AGENTS.md` (collaboration protocol), `README.md` (reproduction steps in Appendix B) |

Everyone also fills in their own row of Table 15 (roles and contributions).

## Open tasks in v1.3

| Area | Task |
|---|---|
| Frontend | Write Section 6.3, User workflow (see below). Replace Figure 2 with a screenshot of the English interface. |
| Testing and evaluation | Rewrite Sections 2.1 and 2.4 and Table 1 using the competitor findings below, and update the matching sentences in Section 1.1. |
| Project management | Confirm the dates in Table 13. Fill in the commit hash and SHA-256 in Appendix B at submission. |
| Everyone | Table 15. |

### Section 6.3, User workflow

Write it as the steps a buyer takes, one or two sentences each, in the same order as the demo video:

1. Describe the home in one sentence (e.g. "3-bedroom house under $1M near a train station, preferably quiet").
2. Check the condition chips the system understood; required and preferred conditions are shown
   separately and can be edited directly.
3. Read the results list and the map together; the "quiet" score on each card shows its evidence
   (e.g. distance to the nearest main road).
4. Open a property's detail panel: valuation range, stamp duty, rental figures with editable
   assumptions, school zone, distance to any place.
5. Refine by typing a follow-up such as "cheaper"; the conditions carry over and the change is explained.

Reuse Figure 3 with annotations where possible instead of adding several full-page screenshots.
The four presentation themes (*One sentence*, *Understands*, *One screen*, *Traceable*) are for the
video and slides only; do not use them as report headings.

## Corrections already made in v1.3 (do not revert)

These statements were checked against the raw evaluation answers and the code:

- **m10, arm B:** it said that none of *its ten retrieved records* qualified and suggested relaxing
  the conditions. It did not claim that no such homes exist. The database contains 631.
- **m1, arm B:** it said its records had no two-bedroom home and offered 3–5-bedroom alternatives,
  the best at **3.69%** (not 3.40%).
- **m10, arm C:** the cards were correct, but the explanation called the second home the
  highest-yielding. A check added on 7 October now removes such claims.
- **o10, arm C:** it said it had no building-age data; it did not say the database has no build year.
- **Model calls:** at most two on the normal path; a first turn misread as a follow-up is parsed once more.
- **"Cheaper":** measured against the median price of the results just shown, not the cheapest one.
- **Abstract and conclusion:** structured figures (not "every number") come from code; intervals
  are a *nominal* 80%; several defects were found and three were fixed and retested.

## Competitor findings (for Chapter 2)

Tested by hand on realestate.com.au on 13 October 2026 (web, signed in and out). The group leader
keeps the screenshots. Describe what we observed and give the date; do not claim more than this.

**What it does well (say so):** a separate "Ask AI" chat (sign-in required) understands full
sentences, keeps conditions across follow-ups and says when it relaxes them, knows which listing
you are viewing on a listing page, gives straight-line distances to a named kind of place (a
station, a café), and answered "the cheapest 3-bedroom house in Glen Waverley" correctly. Its
property pages label data providers per section (PropTrack, Geoscape, ABS) and show planning
overlays (flood, bushfire, heritage), sales history and suburb trends. Its filters for the house
itself (pool, garage, air conditioning) are far richer than ours; our dataset has none of these.

**Where it differs from Nestwise (supported by the tests):**

- **Qualities defined by what is absent are not measured.** For "quietest 3-bedroom houses in Glen
  Waverley" it said that "quietest" is not independently measured and ranked homes by the wording
  of the listing. Its search then used the keyword "quiet", which kept 4 of the 21 matching houses.
  For "away from main roads and industrial areas" it said listing data cannot confirm those
  distances and asked the user to check the map. It declined to assess "safe, low-crime" areas, and
  for "good for families" it picked listings by their wording and asked the user to verify school
  zones. Nestwise scores these qualities for every home from map and official data and shows the evidence.
- **The same question was handled differently on two runs** ("lively, close to cafés": distances
  once, listing keywords the next time). Nestwise's filtering and ranking are done in code.
- **The chat and the results list are on different pages.** After "Go to search" the results page
  has no AI assistant, the AI's ranking and explanation are lost, and refining means using the
  filter panel. Nestwise keeps the conversation, results and map on one screen.
- **Conditions from earlier conversations can reappear.** A new chat applied a $1M budget that
  was not mentioned in it.
- **No per-property analysis on the property page:** no valuation (it links to property.com.au),
  no stamp duty or rental return, and nearby schools are listed by distance rather than by zone.
- **Uncertainty and origin:** estimates carry a low/medium/high confidence level, and AI answers
  carry a general "AI may make mistakes" notice. Nestwise labels each figure's class and gives
  valuations an 80% range.

**Do not write:** that the portal has no AI search, no multi-turn conversation, or no source
labelling, or that it cannot understand any abstract need. Each of these is contradicted by the tests.

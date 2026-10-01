# Nestwise — Feature Guide

What the app can do as of October 2026, screen by screen. Everything listed here is
integrated and working. Limits are stated where they apply.

---

## 1. Homepage

- **3D city showroom** (screens ≥ 900px wide with WebGL): a white-model Melbourne scene,
  pre-rendered in Blender/Cycles and shown with three.js.
  - The camera pans between the **city** view and a set of four **home-type showcase**
    models. Use the left/right arrows to switch; the scene follows the mouse slightly.
  - **Floating signs** carry 40 bilingual example questions, shuffled so no title repeats on
    screen. **Click a sign to run that search.**
- On narrow screens, or when WebGL is unavailable, an illustrated SVG city is shown instead.
- A rotating set of suggested queries, which can be paused.
- **Language switch** (top right): Chinese ↔ English. It translates the whole UI, the
  condition chips, and the AI's explanation (the current answer is regenerated in the new language).

## 2. Asking for a home

Type anything natural, in English or Chinese:

> *"2-bed apartment under $700k close to the city"*
> *"Family house near a good primary school, quiet street, under 1.2M"*
> *"100万内 近车站 3房"*

The assistant understands:

| Kind of request | Examples | How it's handled |
|---|---|---|
| **Hard filters** | budget, bedrooms, bathrooms, property type, suburb | exact SQL filters, never violated |
| **Distance to a place type** | "within 800 m of a train station", "near a school" | straight-line distance from OpenStreetMap data |
| **Lifestyle qualities** (15) | quiet, lively, convenient, shopping, green, beach access, transport, school access, medical, fitness, spacious, family-friendly, away from industry, low crime, away from cemeteries | scored 0–100 from real geographic evidence (percentile against the whole city) |
| **School zones / planning** | "in the X school zone", "no heritage overlay" | official catchment and planning-zone data |
| **Free description** | "renovated-looking period home" | semantic vector search over the listing descriptions |
| **Sorting** | cheapest, most expensive, best rental yield, best ROI | deterministic ranking in code |

**Unsupported questions are named, not guessed.** For example: sunlight or aspect,
renovation condition, school rankings, street-level crime, air or noise measurements,
floor plans, views, future capital growth, and walking/driving time. The assistant
says these can't be answered from the data.

## 3. Results

- **Streaming answer.** The explanation appears word by word. It cites properties by number
  (e.g. "#2 and #4 …"), and clicking a number highlights those cards.
- **Condition card** ("Current filters"). Every filter the assistant applied is shown as a
  chip and can be removed or edited directly. "Add condition" lets you add one by hand, and
  required vs preferred conditions are marked.
- **Property cards** show suburb, address, price, bedrooms/bathrooms/type, reference rent,
  gross yield, distance to the relevant amenity, and badges such as *"valuation 15% above
  sale price"*. Planning or heritage warnings appear as notes.
- **Sort menu**: relevance, price ↑/↓, gross yield, ROI.
- **"Next batch"** pages through the rest of the shortlist (5 at a time).
- **Answer history.** Earlier answers keep their own result set, and you can reopen them and return to the latest.

## 4. Follow-up refinements (multi-turn)

Keep talking and the assistant edits the current search instead of starting over:

- *"cheaper"*, *"a bit quieter"*, *"one more bedroom"*, *"drop the school requirement"*
  - Only what you mention changes; everything else is kept.
  - Relative requests ("cheaper", "quieter") are measured against the **actual current results**.
  - Asking for something "a bit" more means at least a 10-point shift on a 0–100 score.
- **Trade-offs are handled honestly.** Saying "lively" first and then "a bit quieter" keeps
  both qualities and shifts the balance between their scores. If a threshold has to be
  relaxed, the assistant says so.
- If a change leaves no matches, the previous results are kept and you are told why.
  If anything fails, the whole turn rolls back.
- **Suggested follow-ups** under the input box ("quieter", "near a park", "lower budget").

## 5. Map

- Always-visible map panel styled as a frosted-glass slab: a light vector basemap with
  numbered pins matching the cards, and a frosted edge.
  - Panel header: `MAP.VIEW` and live map-centre coordinates.
  - Panel footer: city selector and result count.
  - The city selector currently has Melbourne only; other cities are listed as *coming soon*.
- Controls: **show all results**, zoom in, zoom out. Clicking a card focuses the map on that
  property and highlights its pin; clicking a pin opens the details.
- If WebGL is unavailable, the map falls back to standard OpenStreetMap tiles automatically.

## 6. Property detail panel

A draggable panel (bottom sheet on narrow screens) in five sections:

1. **Price range.** Historical sale price, the **model valuation** (XGBoost, trained on the
   dataset) and its **80% confidence range**, plus a plain-language verdict ("price normal",
   "below / above model range") and how the range was measured.
2. **Location & environment.** Straight-line distances to station, primary school,
   hospital, bank, etc., plus lifestyle scores with their evidence.
   - **Distance tool:** type any place ("Melbourne Uni", "Southern Cross") to measure the
     straight-line distance; a pin and connecting line are drawn on the map.
3. **Purchase cost.** Price + **Victorian stamp duty** (exact statutory brackets, rounded
   per *Duties Act 2000* s 28(1)) + other acquisition costs = total cost.
4. **Rental analysis.** Reference rent (with its source: suburb median, regional
   median, or a labelled assumption), gross yield, operating expenses, NOI, cap rate and ROI.
   - **Editable assumptions:** change the operating-cost rate or other acquisition costs
     right next to the line they affect, and everything recalculates instantly.
5. **Schools, planning & safety.** School catchment zones, planning zone and overlays (e.g.
   heritage), and the LGA crime rate with its city-wide rank.

Each number carries its origin label: measured/statutory, assumption, or model.

## 7. Accounts and favourites

- **Register / log in** from the top-right button. A centred dialog opens over a blurred
  background, with no separate page. Log in with username or email.
  - Passwords are hashed with scrypt; sessions use an HttpOnly cookie.
  - Login attempts are rate-limited (5 failures per 10 minutes).
- **Favourites.** A heart at the bottom-right of every card turns red with a small animation.
  - The header shows a ♥ count; the user menu also opens the favourites drawer.
  - Drawer: compact rows; group by **recent / suburb / price**; search appears once you have more than 20.
  - Opening a favourite shows its **live details** (recomputed with the current
    formulas). Closing the details returns you to the drawer.
  - Favourites keep a snapshot, so they still display if the dataset is re-imported.

## 8. Side-by-side comparison

- Click **"+ Compare"** in a detail panel and pick up to **3** properties from the current
  results or your favourites.
- The columns are aligned section by section, with a **"differences only"** toggle and
  the best value in each row marked.

## 9. Other ways to run it

- **Command line:** `python run.py`, the same engine in a terminal chat.
- **Share publicly:** `python share.py` (or `share-web.bat`) starts the server plus a
  Cloudflare Quick Tunnel and prints a temporary public URL. It has no password, and the URL
  changes on every run.
- **LAN:** `python serve.py --lan` prints an address for phones on the same Wi-Fi.

## 10. What it deliberately does not do

- Show listings or numbers that are not in the data. The no-result path never calls the LLM.
- Estimate travel time. All distances are straight-line.
- Edit the dataset to "fix" data problems. Labels and presentation are fixed instead.
- Mobile-optimised layout. It works on phones, but the design targets desktop.

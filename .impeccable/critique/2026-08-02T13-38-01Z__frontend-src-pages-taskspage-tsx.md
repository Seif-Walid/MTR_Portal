---
target: dashboard (My Tasks landing)
total_score: 21
max_score: 40
na_heuristics: 
p0_count: 1
p1_count: 4
timestamp: 2026-08-02T13-38-01Z
slug: frontend-src-pages-taskspage-tsx
---
Method: dual-agent (isolated sub-agents A: design review · B: detector + browser)

Target: "dashboard" → resolved to the app HOME / landing surface, **My Tasks** (`/tasks`, the default route) — `frontend/src/pages/TasksPage.tsx`.

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 2 | Loading spinner only; no task counts, no "2 overdue / 1 blocked" roll-up; overdue is a faint red date. |
| 2 | Match System / Real World | 3 | Good labels, but PriorityTag SHOUTS in uppercase. |
| 3 | User Control and Freedom | 3 | URL-driven drawer (`?task=id`) gives deep-links + back-button; but no undo, no bulk. |
| 4 | Consistency and Standards | 1 | Breaks its OWN design system — rainbow antd tag colors vs monochrome; selection is ink while the world reserves red for active. |
| 5 | Error Prevention | 2 | "Mark blocked" accepts empty reason; reviewer actions fire with no confirm; optimistic buttons rely on server 403. |
| 6 | Recognition Rather Than Recall | 3 | Columns + tags aid recognition; no legend but filter mirrors vocabulary. |
| 7 | Flexibility and Efficiency | 2 | No search, no column sort, no saved views, no keyboard nav on a daily-driver table. |
| 8 | Aesthetic and Minimalist Design | 2 | Stock look; rainbow tags fight the ink aesthetic; toolbar wraps awkwardly. |
| 9 | Error Recovery | 2 | Generic `message.error`; optimistic-button → 403 dead-clicks. |
| 10 | Help and Documentation | 1 | None; empty state is literal stock "No data" on the home route. |
| **Total** | | **21/40** | **Acceptable — significant improvements needed** |

All ten heuristics apply (Operate landing surface); none scored n/a.

## Design Specificity Verdict

**LLM assessment: Category-interchangeable.** This is a near-stock Ant Design table with a `Segmented + Select + reload + primary` toolbar. Strip the Control-Room shell (dark rail + wordmark, which IS authored) and nothing here says Mind·Tech Robotics, robotics, or even "tasks" — it could be a CRM, helpdesk, or bug tracker. As the app's HOME screen (first thing every member sees each login) that's a real miss. Worse, the surface actively *contradicts* the committed "Control Room" world: it sprays antd default tag colors (processing-blue, warning-gold, success-green, error-red, plus priority orange/blue/red) across the monochrome ink world, violating both the ~90%-monochrome rule and the One Red Rule.

**Deterministic scan:** `detect.mjs` returned **1 finding total** — `layout-transition` (animating `margin` on `AppLayout.tsx:171`, causes reflow; use `transform`). TasksPage.tsx scanned clean, but the detector has blind spots B confirmed by grep/DOM: it missed the hardcoded `#cf1322` overdue color (inline-ternary form) at `TasksPage.tsx:119` and the unlabeled icon-only reload button at `:66`. No false positives — the detector did NOT flag any intentional design-system token (system font, brand hex, flat depth, 6px radius), so there's nothing to excuse.

**Visual overlays:** No user-visible overlay was injected (screenshot capture timed out repeatedly — the known preview flakiness on this app). Evidence was gathered via DOM eval + computed-style inspection instead. Key browser facts: dark theme active, no console errors (only React-Router v7 future-flag warnings); default "Assigned to me" view renders **0 rows → stock "No data"**; at 375px the document `scrollWidth = 1004px` and the page overflows horizontally because the 6-column table has no `scroll={{ x }}`.

## Overall Impression

The *product thinking* is strong and the *surface* is weak. The task **drawer** (role-scoped workflow state machine, plain-English history, batch/team awareness) and the **URL-as-state** deep-linking show real craft — but the landing table they hang off is generic antd that breaks the very design system we just documented. The single biggest opportunity: this is the HOME route, so treat it like one — a calm triage view (caught-up / overdue / blocked / needs-your-review) in strict monochrome-plus-one-red, that works on a phone.

## What's Working

1. **URL-as-state drawer** — `setSearchParams({ task: id })` makes every task deep-linkable and back-button-friendly; genuinely thoughtful control/freedom, rare in a stock antd table.
2. **Role-aware workflow modeling** — `ASSIGNEE_ACTIONS` / `REVIEWER_ACTIONS` plus batch/team surfacing ("Part of a team assignment — N people") shows real domain understanding in the drawer.
3. **The shell executes the world** — `AppLayout`'s dark sider in both themes, the cream wordmark, the sticky bordered (shadowless) header, and the Segmented selection that correctly refuses to color-code by rank.

## Priority Issues

**[P0] The home-screen empty state is a stock "No data" grid.**
- *Why it matters:* This is the default landing route and the most common first impression. On any given day most of a 305-person roster has no assigned tasks — they log in and the home screen says "No data," which reads as *broken / you don't belong* rather than *you're all clear*. Confirmed live: 0 rows, antd default `Empty` at 45% white.
- *Fix:* Author per-view empty states — "You're all caught up ✓ nothing assigned to you" (assigned), an "Assign the first task" CTA for leads (created/all) — and a one-line roll-up ("2 overdue · 1 blocked · 3 need your review") above the table when non-empty.
- *Suggested command:* **/onboard** (then **/delight** the caught-up state).

**[P1] The primary surface overflows horizontally on phones.**
- *Why it matters:* The product explicitly targets students checking tasks one-handed between classes. At 375px the whole page scrolls sideways (`scrollWidth 1004px`) because the 6 fixed-width columns have no `scroll={{ x }}`, and the 560px `TaskDrawer` is dropped onto a 375px screen. The home surface is broken on the primary device.
- *Fix:* Below `lg`, swap the table for a stacked card/list (title + status + due + one-tap open); give the table `scroll={{ x }}` as a floor; make the drawer full-width on mobile.
- *Suggested command:* **/adapt** (with **/layout**).

**[P1] The surface violates its own design system (rainbow tags + un-reserved red).**
- *Why it matters:* `tags.tsx` maps status to processing/warning/success/error and priority to blue/orange/red; the table also shows a red "Blocked" tag, a red overdue date, and red "URGENT" — several competing reds, none reserved. This breaks the ~90%-monochrome rule and the One Red Rule (red ≤10%, reserved for active/danger). On a dense table it's the loudest, noisiest thing on screen.
- *Fix:* Move status to monochrome/ink treatments (weight, a leading dot, hairline borders); let Signal Red mean exactly one thing — "needs your action / danger" (overdue, blocked, revision-requested). Kill the gold/green/blue/orange fills.
- *Suggested command:* **/colorize** (or **/quieter** + token **/harden**).

**[P1] The one CTA fails contrast in dark mode.**
- *Why it matters:* Inspected live — `.ant-btn-primary` is `rgb(211,209,202)` (pale cream) with `color:#fff` ≈ 1.2:1; white-on-cream is effectively illegible. The single primary action ("Assign task") is unreadable in dark mode and fails WCAG badly — and is thus also the quietest thing on the surface.
- *Fix:* Fix the dark-theme primary token so text-on-primary is ink (ink fill + cream text in dark). Verify both themes.
- *Suggested command:* **/harden** (contrast tokens), then **/polish**.

**[P1] Rows aren't keyboard- or screen-reader-operable.**
- *Why it matters:* Task-open is an `onRow.onClick` on a `<tr>` — not focusable, no Enter/Space, not announced as interactive. A keyboard or screen-reader user (Sam) literally cannot open a task, which is the surface's core action. Status/priority severity is also conveyed by tag color alone.
- *Fix:* Make rows keyboard-activatable (focusable, Enter/Space) or add an explicit "Open" affordance; pair every color-coded tag with text/icon so severity isn't color-only; label the icon-only reload button (`aria-label`, `TasksPage.tsx:66`).
- *Suggested command:* **/audit** → **/harden**.

## Persona Red Flags

**Alex (power user):** No title/assignee search, no column sort, no bulk status change, no keyboard nav; refresh is a manual button. "Everything I can see" can't be sliced by assignee or team. Triage is all mouse, all scroll.

**Sam (accessibility / keyboard / screen reader):** (1) `<tr>` row-click isn't focusable or Enter/Space-operable — can't open a task at all. (2) Primary CTA contrast fails (P1). (3) Severity conveyed by tag color alone. (4) Empty state "No data" is non-descriptive to a screen reader on the home route. (5) Reload button has no accessible name.

**Busy student, one-handed on a phone between classes (project persona):** Lands on "No data" or a sideways-scrolling 6-column grid; the overdue signal (tiny dark-red date, no icon/label) is invisible at a glance; opening a task throws a 560px drawer onto a 375px screen; "Assign task" (their least-used action) occupies prime thumb space while "what's due today" gets no emphasis. No "today / this week" 30-second lens.

## Minor Observations

- Overdue uses hardcoded `#cf1322` (antd red-7), not brand Signal Red `#d92d2d` — even the reds disagree with the token file (`TasksPage.tsx:119`).
- `AppLayout.tsx:171` animates `margin` (detector's one finding) — reflow/jank; animate `transform` instead.
- `PriorityTag` renders `priority.toUpperCase()` — visual shouting; sentence case fits the calm Control-Room tone.
- Page title is hardcoded "My Tasks" even in "Assigned by me" / "Everything I can see" views.
- "Mark blocked" accepts an empty reason, so the table can show "Blocked" with no explanation anywhere.
- Reviewer workflow buttons render optimistically and rely on a server 403 → dead-clicks + generic error.
- Header avatar uses `brand.red` — a standing red element eating the ≤10% red budget before any task loads.
- No count context until >15 rows; a lead can't tell "3 tasks" from "300 filtered to 15."

## Questions to Consider

1. If this is the app's *home*, should it even be a raw task table — or a triage dashboard ("Due today · Overdue · Blocked · Needs your review") with the table as the drill-down? What does a member most need in the 30 seconds after login?
2. The world says **red = active/selected**, but the code uses ink for selection and sprays red across status/priority/blocked/overdue. Which is the real rule — and can red mean exactly one thing on this screen?
3. Arabic/RTL is a planned requirement and the roster is Arabic-name-heavy: the toolbar, `Space` gaps, and ellipsis columns all assume LTR — has anyone mirrored this surface, and do Arabic names truncate gracefully in the 180px Assignee columns?

---
name: MTR Portal — CIRCUIT
description: A dark, printed-circuit-board robotics operations portal — near-black panels, electric-blue accent, monospace data labels, glowing borders. Red reserved strictly for alerts.
colors:
  void: "#06080c"
  panel: "rgba(15,20,29,0.55)"
  inset: "rgba(8,11,17,0.6)"
  text-primary: "#eaf2ff"
  text-body: "rgba(224,236,252,0.72)"
  text-muted: "rgba(224,236,252,0.55)"
  text-faint: "rgba(224,236,252,0.4)"
  accent: "#5cc6ff"
  accent-hi: "#7cd2ff"
  accent-lo: "#4eb4f5"
  hairline: "rgba(120,170,230,0.12)"
  violet: "#8b9dff"
  teal: "#4fd6c4"
  steel: "#aab6c6"
  amber: "#ffb26b"
  danger: "#ff3b4e"
  danger-hi: "#ff5a6e"
typography:
  display:
    fontFamily: "'Space Grotesk Variable', 'Space Grotesk', sans-serif"
    fontSize: "22px"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.01em"
  headline:
    fontFamily: "'Space Grotesk Variable', 'Space Grotesk', sans-serif"
    fontSize: "16px"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "normal"
  body:
    fontFamily: "'Geist Variable', 'Geist', -apple-system, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: "normal"
  label:
    fontFamily: "'Geist Mono Variable', 'Geist Mono', monospace"
    fontSize: "9.5px"
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: "0.16em"
rounded:
  sm: "6px"
  md: "8px"
  lg: "12px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "14px"
  lg: "18px"
  xl: "24px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.void}"
    rounded: "{rounded.md}"
    padding: "8px 16px"
  card:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text-body}"
    rounded: "{rounded.lg}"
    padding: "18px"
  input:
    backgroundColor: "{colors.inset}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.md}"
    padding: "6px 12px"
---

# Design System: MTR Portal — "CIRCUIT"

## Overview

**Creative North Star: "The Printed Circuit Board"**

A dark, futuristic operations portal for a robotics team, styled like a live PCB: near-black panels floating over a deep void, an electric-blue accent that reads as a powered trace, monospace labels for every piece of data, and faint hairline borders that glow where something is active. The interface is dense and instrument-like — the team is engineers, and the surface should feel like the machines they build.

It is **dark-only by commitment** (not a theme toggle). Colour is disciplined: the world is near-black + one electric blue, with a small semantic set (violet / teal / steel / amber) tagging sources and states, and **red reserved strictly for alerts** (overdue, low stock, urgent, decline, blocked). The build is a re-skin of the existing React + Ant Design app — routes, data, and API calls are unchanged; the look is delivered by theming Ant Design (ConfigProvider tokens + targeted CSS) plus two bespoke widgets (a spanning-bar calendar and the org tree).

**Key Characteristics:**
- Deep void background with translucent, hairline-bordered panels.
- Electric-blue accent (`#5cc6ff`); gradient + glow on primary actions.
- Monospace, faint, uppercase, letter-spaced labels for all data/columns.
- Red is alerts-only; sources/states carry their own muted hues.
- Dark-only, dense, engineered.

## Colors

### Primary
- **Accent electric blue** (`#5cc6ff`): links, active/selected state, focus, primary buttons (as the `#7cd2ff→#4eb4f5` gradient), calendar "tasks" source. Its glow signals power/activity.

### Secondary (source & state hues — muted, semantic)
- **Violet** (`#8b9dff`): events, automatic roles, item tags.
- **Teal** (`#4fd6c4`): requests, "accepted", direct-report.
- **Steel** (`#aab6c6`): inventory source.
- **Amber** (`#ffb26b`): high priority, "pending", access-level gold.

### Tertiary (alert)
- **Danger red** (`#ff3b4e` / hover `#ff5a6e`): low stock, overdue, urgent, decline, blocked. **Alerts only.**

### Neutral
- **Void** (`#06080c`): app background (deepest).
- **Panel** (`rgba(15,20,29,.55)`): cards, tables, panels over the void (backdrop-blurred).
- **Inset** (`rgba(8,11,17,.6)`): segmented troughs, input fields, sub-headers.
- **Text**: primary `#eaf2ff` · body `.72` · muted `.55` · faint `.4` (labels).
- **Hairline** (`rgba(120,170,230,.12)`) / row divider (`.07`): all borders.

### Named Rules
**The Alert-Red Rule.** Red means *something is wrong or urgent* — overdue, low stock, urgent, declined, blocked — and nothing else. Never a brand colour, never an accent; the electric blue is the accent.

**The Source-Colour Rule.** Each data source keeps one hue everywhere it appears: tasks = accent, events = violet, inventory = steel, requests = teal. A calendar bar, a chip, and a table dot for the same source all share its colour.

## Typography

Three self-hosted voices (bundled woff2, offline/CSP-safe):
- **Display / headings — Space Grotesk** (600): screen titles (22px), card values (28px), section titles (15–18px).
- **Body / UI — Geist** (300–600): all body and control text (13–14px).
- **Data / labels — Geist Mono**: column headers (9.5px, `letter-spacing:.16em`, uppercase, faint), IDs/dates/counts (12–13px), tabular figures.

### Named Rules
**The Mono-Data Rule.** Every column header, ID, date, count, code, and metric is Geist Mono — uppercase and faint for labels, tabular for numbers. Prose and headings never use the mono.

## Layout

The existing app shell: a fixed left nav rail over the void + a sticky, backdrop-blurred top bar. Content in a 24px-margin column. Panels are the unit of grouping (`bg-panel`, hairline, radius 12–14, `overflow:hidden`). Spacing runs ~4 / 8 / 14 / 18 / 24. Density is high; tables are the primary data surface. RTL is a planned requirement — keep logical properties.

## Elevation & Depth

Depth is **light, not shadow**: panels sit above the void by translucency + a hairline border + a faint backdrop blur, and *active* elements glow. Primary buttons carry `0 0 20px rgba(92,198,255,.35)` → hover `0 0 32px rgba(92,198,255,.65)`; today's calendar cell / active nodes glow `0 0 12px rgba(92,198,255,.7)`. A faint cool radial wash sits behind everything as PCB ambiance.

### Named Rules
**The Glow-Means-Live Rule.** A glow marks something powered or current — the primary action, today, the selected node. Static panels don't glow; they use the hairline border. Glow is blue (or red for an alert), never decorative.

## Shapes

Panels/cards `12–14px`; buttons/chips `6–8px`; segmented outer `9–10px`, inner pills `7px`. Borders are single hairlines (`rgba(120,170,230,.12)`); dividers `.07`. Status/meta chips are small, mono, uppercase, with a `1px solid <hue@.35>` border over a `<hue@.08>` fill.

## Components

### Buttons
- **Primary:** accent gradient (`#7cd2ff→#4eb4f5`), void text, weight 600, radius 8, glow (intensifies on hover). Leading `+` for create actions.
- **Ghost / default:** `rgba(255,255,255,.03)` fill, `1px solid rgba(120,170,230,.2)`; hover brightens the border to `rgba(92,198,255,.4)`.
- **Danger:** red gradient variant for destructive actions.

### Segmented control
Trough `bg-inset` + hairline + 4px padding. Active pill: `linear-gradient(90deg, rgba(92,198,255,.2), rgba(92,198,255,.05))` + `1px solid rgba(92,198,255,.3)`, text primary. Inactive transparent, muted. Used for Month/Week, Received/Sent, General/Me, Assigned/Created/All, event-kind, Hide/Show-auto.

### Tables (as circuit panels)
Panel wrapper (`bg-panel`, hairline, radius 12, `overflow:hidden`). Header row: Geist Mono, 9.5px, uppercase, `letter-spacing:.16em`, faint, bottom hairline. Body rows: `padding:14px 18px`, `hairline-row` divider, `cursor:pointer`; hover lifts bg to `rgba(255,255,255,.02)` and reveals a `›` chevron.

### Chips / Tags
Mono 10px uppercase, `1px solid <color@.35>`, bg `<color@.08>`, radius 5. Colour by meaning: violet (item/event/automatic), teal (accepted/direct), amber (pending/priority/level), danger (alert).

### Signature — spanning-bar calendar
Multi-day events render as a **continuous horizontal bar** spanning their days and **continuing across week rows** (clipped ends flatten radius + show `‹`/`›`). Per-week lane packing; Month (6 rows, ≤3 lanes, `+N more`) / Week (single row, ≤8 lanes) toggle. Bars: `bg <src@.15>`, `1px solid <src@.32>`, left accent `3px solid <src>`; multi-day bars glow; overdue uses danger.

### Signature — org tree
The position chart flattened to indented rows (`padding-left = 18 + depth*26`). Each row: glowing accent dot, Space-Grotesk title, occupant names or a dashed `vacant` tag, then tags (`technical` accent, `automatic` violet, access-level amber). A Hide/Show-auto toggle controls the automatic rows.

## Do's and Don'ts

### Do:
- **Do** keep red for alerts only — overdue, low stock, urgent, decline, blocked (The Alert-Red Rule).
- **Do** give each data source its one hue everywhere (The Source-Colour Rule).
- **Do** set every column header, ID, date, count, and metric in Geist Mono (The Mono-Data Rule).
- **Do** convey depth with translucency + hairline borders + a blue glow on *live* elements (The Glow-Means-Live Rule).
- **Do** keep routes, API calls, and data flow exactly as they are — this is a re-skin.

### Don't:
- **Don't** use red as an accent or brand colour; the accent is electric blue.
- **Don't** add a light theme — CIRCUIT is dark-only.
- **Don't** put a heavy drop shadow on a static panel; use the hairline + glow-when-live.
- **Don't** set data/labels in the body or display face — data is mono.
- **Don't** introduce hues outside the palette (accent + violet/teal/steel/amber + danger).

---
name: MTR Portal — Workbench
description: Machined-steel neutrals, ink as the brand voice, the logo's dial-tick red as the single attention signal. Full light and dark themes built on the portable design system (erp-onboarding/portable-design-system).
source_of_truth: frontend/src/theme/tokens.ts
---

# Design System: MTR Portal — "Workbench"

## Overview

The portal follows the portable design system's rules (`DESIGN_RULES.md`: role
tokens, state model, motion, risk tiers, content rules). This file records only
the MTR brand layer and the places the portal applies those rules.

**Identity, taken from the team logo.** The logo is black-and-white machined
metal with a ring of red dial ticks. So:

- **Neutral chrome** is steel grey, slightly cool. Never cream, never pure black.
- **Ink is the brand voice.** Primary buttons, the active nav item, selection and
  the focus ring are ink: near-black in light mode, near-white in dark mode.
- **Signal red means "needs attention"** and nothing else: overdue, blocked,
  unread, live/now, error. Because the brand isn't red, red always reads as a call.
- **Type is one family, Archivo**, using its width axis: wide (118–125%) and heavy
  for display text, echoing the logo's stamped lettering; normal width for UI.
  Geist Mono only for codes and IDs.

## Where things live

| What | File |
|---|---|
| Role tokens (light + dark), system scales, CSS var install | `frontend/src/theme/tokens.ts` |
| antd theme built from the same values | `frontend/src/theme/circuitTheme.ts` (`antdTheme(mode)`) |
| Theme preference (light / dark / system, persisted, circular reveal) | `frontend/src/theme/ThemeContext.tsx` |
| Base layer: shell classes, state model, responsive nets | `frontend/src/theme/base.css` |
| Inline-style shorthands (`C.text`, `C.accent`, `hexA`) — all CSS vars | `frontend/src/theme/circuitTokens.ts` |
| Table and calendar layers | `frontend/src/tables.css`, `frontend/src/calendar.css` |

Components read `var(--role)` only. A hex or rgba literal in a component is a bug:
it will be right in one theme and wrong in the other.

## Colors (role → light / dark)

| Role | Light | Dark |
|---|---|---|
| background | `#f1f2f4` | `#0d0e10` |
| surface | `#ffffff` | `#141619` |
| surface-alt | `#e9ebee` | `#1b1e22` |
| border | `#d9dce1` | `#2a2e34` |
| text-primary | `#121418` | `#eceef1` |
| text-secondary | `#454a53` | `#b3b8c0` |
| primary (fill) / on-primary | `#121418` / `#ffffff` | `#eceef1` / `#0d0e10` |
| signal / signal-text | `#d7263d` / `#b3182d` | `#ff4d5e` / `#ff8a95` |
| cat-blue · violet · teal · amber · steel | categorical marks (calendar sources, kinds, chart series) | |

Semantic `success / warning / error / info` each have hue, `-text` and `-surface`.

## Motion (Motion for React, `motion/react`)

Interaction in the Webflow vein, held to the design system's rules (ease-out
enter, ease-in leave, nothing bounces, reduced motion respected via
`<MotionConfig reducedMotion="user">`):

- **Gliding highlight** — a shared `layoutId` pill slides between hovered items:
  the nav rail, Home's stat tiles, Home's queue rows. One idiom everywhere.
- **Theme switch** — a sliding thumb; the new theme grows out of the click as a
  circle (View Transitions API, instant fallback).
- **Page transition** — 300 ms fade/rise in, 120 ms out; the header title swaps with it.
- **One load moment per page** — on Home, the dial draws its ticks and the hands
  sweep to the time; content rises once, never on refetch.
- Numbers never count up (work context).

## Do's and Don'ts

- Do use `var(--signal)` only for things that need the user now.
- Do give every status a word or icon, not colour alone.
- Do use sentence case for labels; no tracked-out uppercase micro-labels.
- Don't add glow, glass or gradients to data areas.
- Don't add a second motion idiom where the gliding highlight already fits.

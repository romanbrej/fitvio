# Wall Page Overrides

> **PROJECT:** Fitvio
> **Generated:** 2026-09-28 21:44:56
> **Page Type:** Dashboard / Data View

> ⚠️ **IMPORTANT:** Rules in this file **override** the Master file (`design-system/MASTER.md`).
> Only deviations from the Master are documented here. For all other rules, refer to the Master.

---

## Page-Specific Rules

### Layout Overrides

- **Max Width:** 1400px or full-width
- **Grid:** 12-column grid for data flexibility
- **Sections:** 1. Hero (product + live preview or status), 2. Key metrics/indicators, 3. How it works, 4. CTA (Start trial / Contact)

### Spacing Overrides

- **Content Density:** High — optimize for information display

### Typography Overrides

- No overrides — use Master typography

### Color Overrides

- **Strategy:** Dark or neutral. Status colors (green/amber/red). Data-dense but scannable.

### Component Overrides

- Avoid: Single row actions only
- Avoid: Auto-play high-res video loops

---

## Page-Specific Components

- No unique components for this page

---

## Recommendations

- Effects: Hover tooltips, chart zoom on click, row highlighting on hover, smooth filter animations, data loading spinners
- Data Entry: Allow multi-select and bulk edit
- Sustainability: Click-to-play or pause when off-screen
- CTA Placement: Primary CTA in nav + After metrics

---

## Project overrides (decided in planning, take precedence over MASTER)

- **Dark theme by default.** This is a wall display in a living space: glare, burn-in and room ambience beat the light default.
  Tokens live in `frontend/src/theme.css` (`--bg #0B1120`, `--surface #111827`, `--text #E5E7EB`, `--muted #94A3B8`).
- **Verdict states always use icon + word + colour** (never colour alone):
  better = green `#22C55E` / TrendingUp · in line = sky `#38BDF8` / MoveRight · worse = red `#F87171` / TrendingDown ·
  not comparable = slate `#94A3B8` / CircleHelp · load only = violet `#A78BFA` / Activity. Amber `#F59E0B` = warnings (stale sync, context notes).
- **Readable from ~3 m:** verdict word ≥ 88px, key numbers ≥ 36px (Fira Code, tabular), body ≥ 18px.
- **Glance → tap → detail:** every wall card is a ≥ 44px touch target that opens a detail route; detail routes return to the wall after `idle_return_seconds`.
- **Touch only**, no hover-dependent information. Night dimming between `night_start` and `night_end`.
- Fonts are bundled via `@fontsource` (the tablet may be offline from Google Fonts).

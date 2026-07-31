# UI Consistency Audit — DeclaratorLM

Working notes on visual/CSS inconsistencies in `declarator-lm/src/` (React + `index.css`). Started as an ad hoc review of the live-log error cards, expanded into a broader pass across the app. Every item cites `file:line`; items marked **[FIXED]** were already corrected in this repo, the rest are still open.

Scope covered so far: buttons, spinners/pulse animations, gauges, modal structure, dashboard/chart color tokens, icon sizing, the `Toggle` component, typography scale, focus/hover states, empty/error-state messaging, form inputs, and the tooltip system. Not yet covered: full type-scale token migration, border-radius token migration, modal width harmonization — these were diagnosed as systemic (no defined target scale) rather than single bugs, so they're listed as open root causes, not line-item fixes.

---

## 1. Fixed this session

- **`.adv-settings-modal--wide`** was narrower (480px) than the base modal (520px) — a literal name/value contradiction. Fixed to 620px. `index.css:2739`
- **`.dossier-pdot`/`dossier-pulse`** was a byte-for-byte duplicate of `.visual-log-pdot`/`visualLogPulse` (only dot size differed). Merged into one shared rule + `pending-dot-pulse` keyframe; `.dossier-pdot` also gained the `prefers-reduced-motion` exemption it was missing. `index.css:4087-4104`, `4157-4160`
- **Ring-spinner timing** (`autosave-spin` 0.85s, `deep-research-spin` 0.75s **and** 0.88s — three speeds for the same CSS border-trick) unified into one `ring-spin` keyframe at 0.8s across all four call sites.
- **`RiskGauge`/`GaugeRing`** duplicate SVG donut gauge (VisualLogPanel vs DossierPanel, diverging size/timing) consolidated into shared `RiskGauge.jsx`; DossierPanel's copy gained the sweep-in animation and reduced-motion handling it previously lacked entirely.
- **`.dossier-chart-card`** used `var(--surface)` (page-background token) instead of `var(--panel)` (the card token every sibling card uses). Fixed. `index.css:6006`
- **`RISK_COLORS`** was declared twice in `dossierChartConfig.js` (once as the exported object, once again inline as hex literals repeated 6 times across the three chart definitions). Consolidated to one declaration, referenced everywhere.
- **`DashAutoFlipToggle`** in `UsageDashboard.jsx` reimplemented the shared `Toggle` component's markup. Replaced with the real `Toggle` (now exported from `App.jsx`), verified live in a browser to rule out the circular-import risk.
- **`CloudComparisonModal`**'s secondary button read "Закрити" while every other cancel-role button in the app reads "Скасувати" — this modal has real confirm semantics (`OK` launches a run), so it was a genuine label bug, not a stylistic choice. Fixed.
- Card-entry **sheen animation** (`visualLogSheen`) no longer plays on error/limit cards (was reading as a celebratory flourish on a failure state).
- **Tactile press feedback** (hover-lift/active-scale) on `.btn-primary` extended from `.cloud-modal`-only to the base class, so every modal's primary button feels the same; carried the `prefers-reduced-motion` guard along with it.
- Reasoning-debug "💭 thought" line given a proper chip container + 2-line clamp instead of unbounded plain italic text.

Investigated and deliberately **left alone** (justified, not bugs): `CloudSettingsModal`'s footer-bar/spacer layout and `PromptSessionModal`'s 3-button layout both carry a genuine extra action (debug compare-button, reset-to-builtin) that the plain 2-button pattern can't accommodate; `DeepResearchModal`'s red-tinted border matches its own "session theme" (`.app.app--deep-research`, a real, live CSS-variable theme swap, not a one-off).

---

## 2. New findings this round

### Typography — no shared scale, and it shows on same-role text
25 distinct raw `font-size` values in `index.css`, none backed by a token. Two concrete same-role divergences:

- **Card "name" heading** rendered at three different sizes/weights depending which component owns the card: `.visual-log-card-name` 14px/600 (`index.css:3940`), `.dossier-nc-name` 16px/700 (`index.css:5869`), `.usage-dash-top-name` 13.5px/600 (`index.css:5268`, 15px/600 in the `--flow` variant at `5584`). Same semantic slot ("who/what this card is about"), three different weights.
- **Uppercase "eyebrow" label** (small-caps-style section label, muted color, letterspaced, weight 600) implemented three times at three sizes with identical everything else: `.card-title` 11px (`index.css:1673`), `.sort-dropdown-group-label` 10px (`index.css:2542`), `.visual-log-sort-label` 10.5px (`index.css:3647`).

Font-*weight* is not the problem — muted/secondary text (`.field-label`, `.cloud-label`, `.toggle-label`) agrees on 12px/400 everywhere it was checked.

### Focus rings — three unrelated formulas for "this is focused"
- Text-input focus ring: base `.field-input:focus` correctly uses theme tokens (`var(--accent)` / `var(--accent-glow)`, `index.css:1900-1902`) — but `.cloud-modal .field-input:focus` (`index.css:1910-1912`) swaps in **hardcoded** `#3b82f6` / `rgba(37,99,235,…)`. That means every input inside a cloud-style modal shows a fixed blue glow that won't follow the app's own theme-swap mechanism (the real `.app.app--deep-research` red theme, confirmed live elsewhere) — the one input style in the app that's theme-blind.
- Outline-based keyboard focus varies in width and style for comparable controls with no evident reason: `.mode-segment__btn:focus-visible` 2px solid accent (`index.css:280`), `.about-program-link:focus-visible` 1px solid accent (`index.css:2939`), `.tooltip-anchor:focus-visible` 1px **dashed gray** (`index.css:1974`) — three visual languages for the same keyboard-focus job.
- "Active/open" glow rings (`.file-picker-search-toggle--open`, `.queue-btn--active`) agree with each other at `0 0 0 2px var(--accent-glow)` but disagree with the text-input focus ring's `3px` — so "ring width" isn't a fixed constant even within the accent-glow family.
- Hover backgrounds for list rows/dropdown options **are** consistent (`var(--panel-hover)` everywhere checked) — not a finding, just confirming that half of "interaction states" is fine.

### Empty/error-state messaging — no shared language, one real bug
- `.log-empty` (`index.css:3436`) is the one deliberately-designed empty state: centered, spaced, italic, muted — reused identically across 4 call sites in `VisualLogPanel.jsx`/`App.jsx`.
- Everything else invents its own treatment: `.dossier-charts-empty` (`index.css:6148`) is a near-duplicate of `.log-empty` that could have reused it; `UsageDashboard.jsx` alone has **three** different one-off muted-text treatments for what is functionally the same "nothing to show" message (`.usage-dash-sub` at line 398, `.usage-dash-empty-hint` at 423, `.usage-dash-muted` at 509 — three different classes, three different tokens: `--text-muted`, `--text-dim`, and `--text-muted`+italic respectively).
- **Real bug, not just a style gap:** `UsageDashboard.jsx:398` renders "Не вдалось завантажити статистику." (a genuine fetch-failure message) through the plain `.usage-dash-sub` subtitle style — visually indistinguishable from a normal subtitle. A dedicated `.usage-dash-sub--err` modifier already exists in the CSS (`index.css:4933`, sets `color: var(--err)`) but is **never applied** at the one call site that needs it. The error state looks like calm status text.
- **`.cloud-error`** (`index.css:1559`, used at `App.jsx:1498, 2563, 2693, 2914` for real API/form errors) hardcodes `color: #fca5a5` instead of `var(--err)` — the only error text in the app not using the error token — and has no background/padding/icon at all, the bluntest "afterthought" treatment found in this audit.
- Least-designed: the deep-research folder picker's empty state is a disabled `<option>` string with zero styling (`App.jsx:2755`), and the wipe-traces "nothing found" message is a transient status-bar string, not a UI state at all.

### Form inputs & tooltips
- Text inputs are otherwise well-consolidated onto `.field-input` — the one exception is the same hardcoded-focus-color issue noted above under Focus rings.
- **Three separate tooltip/hint mechanisms coexist**: (1) the real system — `PortalTooltip`/`TooltipWrap`/`LabelWithTooltip` (`App.jsx:573,647,670`), portal-rendered, 600ms delay; (2) plain native `title=` attributes used for hover hints in parallel in at least 6 places (`App.jsx:1394,1436,2541,3753,3771,6092`) — these get instant browser-default tooltip styling instead of the app's own bubble; (3) `.dossier-tooltip` (`index.css:6155`, used only in `DossierCharts.jsx:318`), a fully separate bespoke implementation with its own background/radius/padding/font-size/z-index, sharing nothing with the primary tooltip system.
- Scrollbars: **no issue found** — the global `::-webkit-scrollbar` rule and the Firefox `scrollbar-color` pairs all reference the same tokens everywhere checked (log feed, modal bodies, file-picker table, comboboxes).

---

## 3. Open systemic root causes (not line-item bugs — need a deliberate token decision before touching)

- **No spacing/radius scale**: `border-radius` alone spans 2/3/4/5/6/7/8/9/10/11/12/13/14px plus `50%`/`99px`/`999px`, no `--radius-*` step system beyond the single `--radius: 6px` that's bypassed constantly.
- **No icon-size scale**: "small circular icon" role lands on 22/26/28/30/34/38/42/52/64px across different components with no tiering.
- **No font-size scale**: see Typography above — 25 raw values, no tokens.
- **Modal width scale**: 520/540/560/640/720/920px, mixed `vw`/`calc()` units, no shared step system.

Recommendation stays the same as previous rounds: these need someone to actually pick a target scale (e.g. 4 radius steps, 4 icon-size steps, a type scale) before a sweep is worth doing — mechanically normalizing ~80+ call sites to arbitrary "closest existing value" would just relocate the arbitrariness, not fix it.

---

## 4. Suggested next fixes, ranked by cost/value

1. `UsageDashboard.jsx:398` — apply the already-existing `.usage-dash-sub--err` class to the fetch-failure message. One JSX attribute, fixes a real "error looks like calm status text" bug.
2. `.cloud-error` — swap hardcoded `#fca5a5` for `var(--err)`. One CSS value, brings the app's most-used inline error class onto the token system.
3. `.cloud-modal .field-input:focus` — swap hardcoded `#3b82f6`/`rgba(37,99,235,…)` for `var(--accent)`/`var(--accent-glow)`, matching the base rule's comment ("softer focus ring") while staying theme-aware.
4. Eyebrow-label trio (`.card-title`/`.sort-dropdown-group-label`/`.visual-log-sort-label`) — pick one size (10.5px is the middle value) for all three; lowest-risk of the typography findings since they already share every other property.
5. Native `title=` attributes vs the `TooltipWrap` system — either intentional (quick native hints for low-priority spots) or drift; worth a decision, not a mechanical fix.

---

*Generated by a code-level audit (grep + targeted reads across `index.css`, `App.jsx`, `VisualLogPanel.jsx`, `DossierPanel.jsx`, `DossierCharts.jsx`, `UsageDashboard.jsx`, `dossierChartConfig.js`). No live screenshot was taken this round; every claim above is backed by a file:line citation, not a visual impression.*

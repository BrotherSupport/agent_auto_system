# FinLab — Data-Dense Pro

Reference DESIGN.md for a clean, bilingual fintech/quant-research platform that pairs conversational AI with dense financial data.

## 1. Visual Theme & Atmosphere

Sophisticated accessibility. A quant trading platform that doesn't intimidate — data-dense but approachable, white-canvas primary, blue accent system, conversational AI as the UI centrepiece.

Mood: credible, analytical, quietly modern. Less Bloomberg terminal, more "Bloomberg for everyone."

## 2. Color Palette & Roles

```
--bg:              #ffffff
--bg-alt:          #f9fafb
--surface:         #f3f4f6
--surface-raised:  #ffffff   /* card / dialog */
--text:            #111827
--text-muted:      #6b7280
--text-dim:        #9ca3af
--border:          #e5e7eb
--border-strong:   #d1d5db

--accent:          #2563eb   /* primary blue — CTAs, links, focus */
--accent-hover:    #1d4ed8
--accent-light:    #eff6ff   /* tint for badges, highlights */

/* data / chart series */
--series-gain:     #16a34a   /* green — positive returns */
--series-loss:     #dc2626   /* red — negative returns */
--series-neutral:  #6b7280
--series-1:        #2563eb
--series-2:        #7c3aed
--series-3:        #0891b2
--series-4:        #d97706
--series-5:        #db2777

--success:         #16a34a
--warning:         #d97706
--danger:          #dc2626
```

Rule: never use red/green outside of financial gain/loss context — colour-blind users must rely on sign (+/−) as well as colour.

## 3. Typography Rules

- **UI / body:** `Inter`, system-ui fallback. Tabular numerals always on (`font-variant-numeric: tabular-nums`) for any price, return, or metric column.
- **Display / hero:** Inter, weight 700–800, tight tracking.
- **Mono / code / tickers:** `JetBrains Mono`, `SF Mono`. Use for ticker symbols, backtest IDs, API keys, code snippets.
- **CJK fallback:** `Noto Sans TC`, `PingFang TC`, system-ui — FinLab serves Taiwanese/Japanese/Korean audiences; always include CJK stack.

Scale: 12 / 13 / 14 / 16 / 18 / 20 / 24 / 32 / 40 / 56.

12–14px dominates dashboard views. 32–56px reserved for hero metrics and landing page display.

## 4. Component Stylings

**Pricing cards**
- Free tier: `--surface` background, `--border` 1px, radius 12px.
- VIP tier: `--accent` border (2px), subtle `--accent-light` background tint, "Popular" badge.
- Feature list: checkmarks in `--success`, crossed items in `--text-dim`.

**Backtest result tables**
- Row height 32px. Zebra `--bg-alt` on odd rows.
- Numeric columns right-aligned, mono font.
- Return cells color-coded: positive → `--series-gain`, negative → `--series-loss`.
- Sticky header, sticky ticker column.

**Conversation / AI chat UI**
- User bubble: `--accent` fill, white text, border-radius 12px 12px 2px 12px.
- AI bubble: `--surface` fill, `--text` color, border-radius 12px 12px 12px 2px.
- Code/query blocks inside bubbles: mono 12px, `--bg` background, `--border` outline.

**Buttons**
- Primary: `--accent` fill, white text, radius 8px, padding 10/20, weight 600.
- Secondary: `--surface` fill, `--text` color, `--border-strong` 1px outline.
- Destructive: `--danger` fill, white text.

**Badges / tags**
- Pill, 20px tall, 12px font, uppercase or title-case.
- Strategy type, asset class, timeframe — use `--accent-light` + `--accent` text.

**Inputs**
- `--bg` fill, 1px `--border`, radius 6px.
- Focus: 2px `--accent` ring, 2px offset.
- Mono font for any input accepting a ticker or formula.

## 5. Layout Principles

- Marketing pages: 1280px max, 24px gutter, 12-column.
- Dashboard / research app: full-viewport, resizable panels, no max-width.
- 4px base grid. Spacing scale: 4 / 8 / 12 / 16 / 24 / 32 / 48 / 64.
- Left sidebar 240px (strategy list / watchlist), collapsible to 56px icon rail.
- Chart area gets 60–70% of horizontal space; params panel gets remainder.

## 6. Depth & Elevation

Light canvas — depth via background steps (`--bg` → `--bg-alt` → `--surface`).

Shadows sparingly:
- Cards: `0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04)`
- Dropdowns/modals: `0 8px 24px rgba(0,0,0,0.10)`

No neumorphism. No heavy gradients. Glassmorphism only for overlay panels, not primary surfaces.

## 7. Do's and Don'ts

**Do**
- Tabular numerals everywhere money or percentages appear.
- Mono font for tickers, strategy IDs, formula strings.
- Use + / − prefix on return values alongside colour.
- Always include CJK font stack (TC first, then SC, JP, KR).
- Keep AI conversation UI visually distinct from static UI chrome.
- Show confidence intervals on backtest charts — never just a single equity curve.

**Don't**
- Use red/green for anything other than financial gain/loss.
- Animate charts for longer than 300ms (distracts from data reading).
- Center-align numeric columns.
- Use decorative illustrations in the dashboard — save them for the marketing hero only.
- Apply font-weight below 400 for body text (legibility at small sizes).

## 8. Responsive Behavior

- Mobile (< 768px): collapse sidebar to bottom-tab-bar; single metric card per viewport; swipe between backtest results.
- Tablet (768–1024px): two-column layout; chart + condensed params panel.
- Desktop first for research/dashboard views — do not force full feature parity into 375px.

## 9. Internationalisation Notes

- Date format: YYYY-MM-DD in data, localised display (e.g. "2026年6月23日") via Intl.DateTimeFormat.
- Number separators follow locale: `1,234.56` (en), `1.234,56` (de-style), `1,234.56` (zh-TW typical).
- RTL: not currently required but keep layout flex-direction reversible.

## 10. Agent Prompt Guide

Bias: white canvas, Inter + CJK stack, tabular numerals, blue accent (#2563eb), 4px grid, dense data tables with sticky headers, mono for all financial identifiers, gain/loss colour pair (#16a34a / #dc2626).

Reject: dark primary canvas, decorative illustrations inside dashboards, non-tabular numerals, serif fonts, shadows on buttons, using red/green for non-financial meaning.
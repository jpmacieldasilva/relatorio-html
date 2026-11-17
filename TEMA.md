# Temas do relatório (TEMA.md)

The whole look of a report lives in one **theme** JSON: fonts, colors, data palette, shapes, spacing, type scale, hero and motion. The template reads only CSS custom properties, so a theme never touches the layout code. `tema.py` resolves the theme, validates it, checks contrast and inlines the fonts and logo. The result still opens offline.

## Choosing a theme

The spec field `theme` (or `build.py --theme …`) takes one of three forms:

| Value | Result |
|---|---|
| omitted / `None` | `temas/neutro.json`, the default |
| `"corporativo"`, `"jornal"`, `"noturno"`, `"destaque"` | a preset from `temas/` |
| `"minha-marca.json"` | a theme file (relative to the spec's folder); it may start with `"extends": "corporativo"` |
| `{...}` | inline overrides, deep-merged onto the default (or onto `"extends"`) |

The briefing-card shorthands are valid inline:

```python
spec["theme"] = {"primary": "#0B5FFF", "accent": "#7FB2FF", "font": "Inter", "heading": "Fraunces",
                 "logo": "logo.svg", "brand": "Acme"}
```

| Shorthand | Expands to |
|---|---|
| `primary` | `colors.primary` (hero / band blocks, "down" deltas) |
| `accent` | `colors.accent` (main data color) |
| `font` | heading + body fonts |
| `heading`, `body`, `mono` | that font role |
| `logo`, `brand` | `brand.logo`, `brand.name` |

Preview any theme without building a report:

```bash
python3 tema.py jornal          # warnings + contrast report
python3 tema.py temas/noturno.json --css
```

## Presets

| Preset | Layout | Look |
|---|---|---|
| `neutro` (default) | `clean` | Inter + IBM Plex Mono. Off-white page `#FAFAF9`, grey ink scale, deep blue `#1F4E79` as primary (kickers, active states, lines), data in `#3A78B5`, colorblind-safe categorical palette (blue, orange, teal, rose, purple, olive…), blue ↔ orange for good/bad. Plain header with a hairline, a 52 px title on the page color, KPIs as cards, 10 px radius, light footer, subtle motion (0.65×). |
| `corporativo` | `blocks` | IBM Plex Sans / Plex Mono. Navy `#0B2545` hero and KPI band, blue `#4F8EDC` data, 4 px radius, calmer motion (0.8×). |
| `jornal` | `clean` | Newsreader serif headings, Inter body, cream page, red `#B3261E` primary, petrol-blue data, square corners. |
| `noturno` | `blocks` | Dark by default. Space Grotesk / Inter / JetBrains Mono, lime `#C6F432` blocks, cyan `#67D4F5` data. |
| `destaque` | `blocks` | Archivo + IBM Plex Mono. Sun-yellow `#F6C945` hero and band, petrol `#1F7A8C` data, big headings. For presentations and covers. (`"editorial"` is accepted as an old alias.) |

### Layouts (`layout.style`)

| Style | What changes |
|---|---|
| `clean` (default) | The hero sits on the page color: colored kicker, moderate title, meta on the left. The statement reads as a paragraph and the KPIs are cards in one row (up to 6). Highlights get a thin left rule. The footer is light with no wordmark. Intro motion is a short fade-up of the title and the cards. |
| `blocks` | The hero and the statement + KPI band are full-bleed `primary` color with big type. KPI columns are separated by hairlines. The footer is dark with the brand wordmark. The hero opens taller and settles. `hero.art: true` adds the optional data-driven dot-matrix strip under the hero (off in every preset). |

Shared by both: a plain header bar (brand or logo, "Sumário", theme toggle, PDF) that hides on scroll; a chapter menu that slides in as a side drawer; and a sticky left TOC with a hairline rail and a primary-color bar on the active chapter.

## Format

```jsonc
{
  "name": "Minha marca", "extends": "neutro",         // optional parent
  "layout": { "style": "clean", "areaOpacity": 0.14 },  // clean | blocks; fill opacity of single-series areas
  // layout grid (px): page max width, menu rail, rail→content gap, 12-column gutter, outer padding.
  // header zone (hero, filters, summary, KPIs, highlights) = maxWidth − 2·pad (1376 px); sections use the content
  // column = maxWidth − 2·pad − rail − railGap (1128 px), the rail holding the menu. All blocks span 12 / 6 / 4 columns.
  //   "grid": { "maxWidth": 1440, "rail": 200, "railGap": 48, "gutter": 32, "pad": 32 }
  "mode": "auto",                                       // auto | light | dark (initial theme; the toggle stays)
  "brand": { "name": "Acme", "logo": "logo.svg" },      // logo: path, URL or data URI → inlined (SVG/PNG < ~100 KB)
  "fonts": {
    "heading": { "family": "Fraunces", "source": "google", "weights": [500, 600], "fallback": "serif" },
    "body":    "Inter",                                  // shorthand: Google if available, else system
    "mono":    "system:Menlo"                            // or "file:fonts/Marca.woff2", "bundled:Geist Mono"
  },
  "colors": {
    "primary": "#0B5FFF",                                // kicker + active states (clean) / hero + band blocks (blocks)
    "accent":  "#7FB2FF",                                // single-series data, highlights
    "light": { "bg": "#FFFFFF", "surface": "#FFFFFF", "surface2": "#F5F6F8", "ink": "#0A0A0A",
               "muted": "#5F6670", "faint": "#9AA0A8", "rule": "#E3E5E8", "ruleStrong": "#0A0A0A",
               "context": "#E3E5E8", "line": "#0B3FA8", "footerBg": "#F1F2F4", "brandBg": "#FFFFFF", "artBg": "#F1F2F4" },
    "dark":  { "...": "same keys; primary / accent may be overridden per mode" }
  },
  "palette": {
    "categorical": ["#7FB2FF", "#0B5FFF", "..."],       // series and categories, in order
    "sequential":  ["#F5F6F8", "#7FB2FF", "#0B3FA8"],    // heatmaps (low → high); optional sequentialDark
    "diverging":   ["#C2410C", "#FDBA8C", "#E5E7EB", "#93C5FD", "#1D4ED8"],  // Likert / NPS (bad → good)
    "positive": "#7FB2FF", "negative": "#0B5FFF"         // ▲ / ▼ and better/worse than the rest
  },
  "shape": { "radius": 10, "rule": 1, "ruleStrong": 1, "ruleSection": 1 },  // px
  "space": { "section": 96, "chartGap": 64, "band": 40 },                   // px at 1440 wide; scale down fluidly
  "type":  { "hero": 52, "h2": 30, "chartTitle": 18, "kpi": 40, "kpiLabel": 14, "dek": 19, "body": 16,
             "headingWeight": 600, "tracking": 0.35, "heroLineHeight": 1.1 },  // tracking multiplies the negative letter-spacing
  "hero":  { "style": "plain", "art": false },          // blocks layout: block = full-bleed color, plain = page color; art = dot-matrix strip
  "motion": { "enabled": true, "speed": 0.65 }           // speed multiplies every duration (0.5 = twice as fast)
}
```

Every key is optional in an override. Anything missing comes from the parent.

## Fonts

| Source | Behavior |
|---|---|
| `google` | Downloads the latin and latin-ext `woff2` once and caches it in `vendor/fonts-cache/`. Variable fonts are de-duplicated into one weight range. The font is inlined as base64, typically 40–180 KB per family. |
| `file` | Local `.woff2` / `.woff` / `.ttf` / `.otf`, either one file or `"files": {"400": "a.woff2", "700": "b.woff2"}`. |
| `system` | Nothing is embedded. The family name is followed by the fallback stack, so it only shows on machines that have it installed. |
| `bundled` | Geist and Geist Mono ship with the kit (OFL) as an offline option (`"bundled:Geist"`). No preset uses them. |

A plain name like `"Inter"` tries Google first. If the download fails or the box is offline, it falls back to a system font and prints a warning.

## Validation and contrast

`build.py` prints every `theme:` message.

- **Problems** stop the build unless you pass `--loose` / `strict=False`. These are unknown keys, bad hex values, bad modes or hero styles, short palettes and out-of-range numbers.
- **Warnings** are only printed. These are contrast notes, a font falling back to the system, a missing logo or font file, and a heavy logo.
- Text contrast is checked against WCAG 2.x:
  - `ink` on `bg` and `surface` and `muted` on `bg` are checked in both modes. Anything below **4.5:1** gets a warning.
  - Ink on colored blocks is **chosen automatically**: black or white, whichever is readable on `primary`, `footerBg` and `brandBg`. This covers hero and band text, KPI numbers and footer text.
  - Muted text on those blocks is mixed toward that ink until it reaches 4.5:1.
  - Values printed on Likert / NPS segments use the readable ink for each diverging color.
- Data colors are fills, never small text. A pale `accent` is fine for bars. If you need it as text, the template derives a darker text variant.

## Mapping the briefing answers ("brand look")

| The user says | Override |
|---|---|
| "our color is #0057FF" | `{"primary": "#0057FF"}`; also set `accent` to a lighter tint of it, or keep the default blue if it clashes |
| "use Montserrat / our font is X" | `{"font": "Montserrat"}` (or `heading` only for titles) |
| "here's the logo" (file in the chat) | save it next to the spec; `{"logo": "logo.svg", "brand": "Acme"}` |
| "more sober / corporate" | the default `neutro`, or `"corporativo"` for a navy block hero (then override `primary`) |
| "bold, for a presentation" | `"destaque"` or `{"layout": {"style": "blocks"}, "hero": {"style": "block"}}` |
| "dark", "for a TV wall" | `"noturno"`, or `{"mode": "dark"}` |
| "no animation" | `{"motion": {"enabled": false}}` |
| "it's a newspaper-style piece" | `"jornal"` |

Legacy spec keys `meta.accent` and `meta.hero` still work. They map to `colors.accent` and `colors.primary`.

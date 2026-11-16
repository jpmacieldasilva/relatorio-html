# Temas do relatório (TEMA.md)

The whole look of a report lives in one **theme** JSON: fonts, colors, data palette, shapes, spacing, type scale, hero and motion. The template reads only CSS custom properties, so a theme never touches the layout code. `tema.py` resolves the theme, validates it, checks contrast and inlines the fonts and logo. The result still opens offline.

## Choosing a theme

The spec field `theme` (or `build.py --theme …`) takes one of three forms:

| Value | Result |
|---|---|
| omitted / `None` | `temas/editorial.json`, the default |
| `"corporativo"`, `"jornal"`, `"noturno"` | a preset from `temas/` |
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

| Preset | Look |
|---|---|
| `editorial` (default) | Geist / Geist Mono. Flat orange `#FE7445` blocks, lavender `#CDABFE` data, black ink and rules, huge tight headings, square corners, dot-matrix art strip under the hero. |
| `corporativo` | IBM Plex Sans / Plex Mono. Navy `#0B2545` blocks, blue `#4F8EDC` data, 4 px radius, no art strip, calmer motion (0.8×). |
| `jornal` | Newsreader serif headings, Inter body. Red `#B3261E` accent, plain hero (no color block), newspaper rules. |
| `noturno` | Dark by default. Space Grotesk / Inter / JetBrains Mono, lime `#C6F432` blocks, cyan `#67D4F5` data. |

## Format

```jsonc
{
  "name": "Minha marca", "extends": "editorial",      // optional parent
  "mode": "auto",                                       // auto | light | dark (initial theme; the toggle stays)
  "brand": { "name": "Acme", "logo": "logo.svg" },      // logo: path, URL or data URI → inlined (SVG/PNG < ~100 KB)
  "fonts": {
    "heading": { "family": "Fraunces", "source": "google", "weights": [500, 600], "fallback": "serif" },
    "body":    "Inter",                                  // shorthand: Google if available, else system
    "mono":    "system:Menlo"                            // or "file:fonts/Marca.woff2", "bundled:Geist Mono"
  },
  "colors": {
    "primary": "#0B5FFF",                                // hero, band, chapter menu, "down" deltas
    "accent":  "#7FB2FF",                                // single-series data, highlights
    "light": { "bg": "#FFFFFF", "surface": "#FFFFFF", "surface2": "#F5F6F8", "ink": "#0A0A0A",
               "muted": "#5F6670", "faint": "#9AA0A8", "rule": "#E3E5E8", "ruleStrong": "#0A0A0A",
               "context": "#E3E5E8", "footerBg": "#0A0A0A", "brandBg": "#0A0A0A", "artBg": "#0A0A0A" },
    "dark":  { "...": "same keys; primary / accent may be overridden per mode" }
  },
  "palette": {
    "categorical": ["#7FB2FF", "#0B5FFF", "..."],       // series and categories, in order
    "sequential":  ["#F5F6F8", "#7FB2FF", "#0B3FA8"],    // heatmaps (low → high); optional sequentialDark
    "diverging":   ["#C2410C", "#FDBA8C", "#E5E7EB", "#93C5FD", "#1D4ED8"],  // Likert / NPS (bad → good)
    "positive": "#7FB2FF", "negative": "#0B5FFF"         // ▲ / ▼ and better/worse than the rest
  },
  "shape": { "radius": 0, "rule": 1, "ruleStrong": 2, "ruleSection": 1 },   // px
  "space": { "section": 120, "chartGap": 88, "band": 56 },                  // px at 1440 wide; scale down fluidly
  "type":  { "hero": 120, "h2": 40, "chartTitle": 24, "kpi": 85, "kpiLabel": 24, "dek": 32, "body": 16,
             "headingWeight": 500, "tracking": 1, "heroLineHeight": 0.95 },  // tracking multiplies the tight letter-spacing
  "hero":  { "style": "block", "art": true },           // block = full-bleed color; plain = page color, no block
  "motion": { "enabled": true, "speed": 1 }              // speed multiplies every duration (0.5 = twice as fast)
}
```

Every key is optional in an override. Anything missing comes from the parent.

## Fonts

| Source | Behavior |
|---|---|
| `google` | Downloads the latin and latin-ext `woff2` once and caches it in `vendor/fonts-cache/`. Variable fonts are de-duplicated into one weight range. The font is inlined as base64, typically 40–180 KB per family. |
| `file` | Local `.woff2` / `.woff` / `.ttf` / `.otf`, either one file or `"files": {"400": "a.woff2", "700": "b.woff2"}`. |
| `system` | Nothing is embedded. The family name is followed by the fallback stack, so it only shows on machines that have it installed. |
| `bundled` | Geist and Geist Mono ship with the kit (OFL). |

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
| "our color is #0057FF" | `{"primary": "#0057FF"}`; also set `accent` to a lighter tint of it, or keep the default lavender if it clashes |
| "use Montserrat / our font is X" | `{"font": "Montserrat"}` (or `heading` only for titles) |
| "here's the logo" (file in the chat) | save it next to the spec; `{"logo": "logo.svg", "brand": "Acme"}` |
| "more sober / corporate" | `"corporativo"` (then override `primary`) |
| "dark", "for a TV wall" | `"noturno"`, or `{"mode": "dark"}` |
| "no animation" | `{"motion": {"enabled": false}}` |
| "it's a newspaper-style piece" | `"jornal"` |

Legacy spec keys `meta.accent` and `meta.hero` still work. They map to `colors.accent` and `colors.primary`.

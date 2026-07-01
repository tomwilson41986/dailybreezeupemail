# Email Style Guide

The house style shared by every email this project sends — **Breeze-up
graduates**, **Sales catalogues** and **Barrier-trial watchlist**. Reproduce
it anywhere by following the tokens and component recipes below.

The look is a quiet, editorial "bloodstock broadsheet": warm paper-grey page,
white cards with hairline borders, a strict grey type hierarchy, and colour
used *only* to encode meaning (rating strength, finishing position, status).
Everything is inline-styled HTML tables so it survives Gmail, Apple Mail and
Outlook.

Source of truth: the three `src/*/templates/email.html.j2` files and
`src/dailybreezeup/silks.py` / `emailer.py`.

---

## 1. Golden rules (non-negotiable for email)

1. **All CSS is inline** on the element's `style=` attribute. No `<style>`
   block, no classes, no external stylesheet — most clients strip them.
2. **Layout is built from `<table>`s**, not `<div>` fl/grid. Every layout
   table uses `cellpadding="0" cellspacing="0" border="0"`. `<div>`s are used
   only for text runs *inside* a cell.
3. **Every message is `multipart/alternative`** — a plaintext part *and* the
   HTML part (see §10). Never send HTML-only.
4. **Images are inline CID attachments**, never hot-linked (see §8).
5. **Colour carries meaning.** Greys = hierarchy; green/amber/neutral =
   value bands; gold/silver/bronze = podium. Don't add decorative colour.

---

## 2. Colour scheme

### Page & surface
| Token | Hex | Use |
|---|---|---|
| Page background | `#f4f4f1` | `<body>` — warm paper grey |
| Card / surface | `#ffffff` | every card, table, tile-less panel |
| Card border | `#e3e3de` | `1px solid` hairline around cards |
| Row divider | `#efefe9` | `border-top` between table rows |

### Text hierarchy (all greys, warm-neutral)
| Token | Hex | Use |
|---|---|---|
| Ink (primary) | `#1a1a1a` | headings, horse names, key values |
| Body dark | `#444444` | inline body text, secondary emphasis |
| Body | `#555555` | pedigree line, descriptions |
| Muted | `#666666` | section headers, subtitles |
| Label grey | `#888888` | eyebrow labels, table `<th>`, meta |
| Faint | `#999999` | small-sample rows, tertiary meta |
| Footnote | `#aaaaaa` | closing source/footer note |
| Hairline text | `#bbbbbb` / `#cccccc` | `|` and `·` separators |

### Accent
| Token | Hex | Use |
|---|---|---|
| Link blue | `#1a5fb4` | all hyperlinks + linked horse/course names |

Links are **`#1a5fb4`, `text-decoration:none`, `font-weight:600`**. No
underline; weight + colour signal the link.

### Semantic swatch families
These five families drive every tile and badge. Each is a `(background,
foreground, label)` triple.

| Meaning | Background | Foreground | Label text |
|---|---|---|---|
| **Strong / won / active** (green) | `#cce5cc` | `#1f4a1f` | `#3c6c3c` |
| **High** (mid-green) | `#e3f0e3` | `#2d5b2d` | `#557a55` |
| **Mid / placed / new** (amber) | `#f5efde` | `#6a5a30` | `#8a7a4f` |
| **Low / ran / other** (neutral) | `#ececec` | `#555555` | `#888888` |
| **Empty / n-a** (paper) | `#f0f0ec` | `#666666` | `#888888` |
| **Online / silver** (slate) | `#e2e6ea` | `#3d4750` | — |

Podium accents (finishing position only):

| Place | Background | Foreground |
|---|---|---|
| 1st — gold | `#fce99c` | `#7a5a00` |
| 2nd — silver | `#e2e6ea` | `#3d4750` |
| 3rd — bronze | `#f0d9bf` | `#7a4a1a` |
| other | `#ececec` | `#444444` |

---

## 3. Typography

**Font stack** (system-native, no web fonts — they don't load reliably in
mail clients):

```
font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;
```

Set once on `<body>`; every element inherits it.

| Role | Size | Weight | Tracking | Colour | Extras |
|---|---|---|---|---|---|
| H1 masthead | 22px | 600 | `-0.01em` | `#1a1a1a` | — |
| Masthead subtitle | 13px | 400 | — | `#666` | date · count |
| H2 section header | 13px | 700 | `0.06em` | `#666` | `UPPERCASE` |
| H3 sub-section | 12px | 700 | `0.06em` | `#666` | `UPPERCASE` |
| Table `<th>` | 10px | 700 | `0.08em` | `#888` | `UPPERCASE` |
| Tile label (eyebrow) | 10px | 700 | `0.10em` | band label | `UPPERCASE` |
| Tile value | 26–28px | 700 | — | band fg | big number |
| Card title (horse/sale) | 17px | 600 | — | `#1a1a1a` | linked → blue |
| Body / race line | 13–14px | 400 | — | `#1a1a1a` | — |
| Pedigree / detail | 12–13px | 400 | — | `#555` | — |
| Micro-labels (field) | 9px | 700 | `0.06em` | `#999` | `UPPERCASE` |
| Badge / pill | 11–13px | 700 | `0.04em` | band fg | — |
| Footer note | 11px | 400 | — | `#aaa` | `line-height:1.5` |

The system is essentially **three type sizes doing all the work**: a big bold
number (tiles), a 17px semibold title, and a 10–13px grey supporting scale.
Uppercase + letter-spacing is the recurring device for labels and headers.

---

## 4. Layout & spacing

```
<body> #f4f4f1, padding:24px
 └ container: max-width:920px; margin:0 auto
    ├ masthead (H1 + subtitle),           margin-bottom:20px
    ├ H2 section header,                   margin:24px 0 10px  (32px above a 2nd major block)
    │   └ card / table,                    margin-bottom:12px
    │   └ card …
    └ footer <p>,                          margin-top:24px
```

Spacing constants:

- **Page gutter:** `padding:24px` on body.
- **Content width:** `max-width:920px`, centred. Cards are full-width inside.
- **Card inner padding:** `14px 16px` (top-row cells); tighten trailing rows
  to `6px 16px 14px`.
- **Gap between cards:** `margin-bottom:12px`.
- **Corner radius:** `8px` for cards & tiles, `10px` for badge pills, `4px`
  for the silk image.
- **Row separators inside tables:** `border-top:1px solid #efefe9` on each
  `<td>` (borders go on cells, not rows, for client support).

Card skeleton (the unit everything is built from):

```html
<table cellpadding="0" cellspacing="0" border="0" width="100%"
       style="background:#fff;border:1px solid #e3e3de;border-radius:8px;margin-bottom:12px;">
  <tr>
    <!-- optional silk cell (56px) -->
    <!-- identity cell (title + sub) -->
    <!-- right-aligned rating tile(s), width:1%; white-space:nowrap -->
  </tr>
  <!-- additional full-width rows: colspan across all columns -->
</table>
```

Right-hand tiles are pinned with `text-align:right;width:1%;white-space:nowrap`
so they hug the edge while the identity cell flexes.

---

## 5. Components

### 5.1 Masthead
H1 title + one grey subtitle line carrying the date and a running count:

```html
<h1 style="margin:0;font-size:22px;font-weight:600;letter-spacing:-0.01em;">Breeze-up graduates</h1>
<p style="margin:4px 0 0;color:#666;font-size:13px;">
  Wednesday 01 July 2026 &middot; 3 horses
</p>
```
Date format: `%A %d %B %Y`. Separator between facts is ` &middot; ` (`·`).

### 5.2 Section header
```html
<h2 style="font-size:13px;font-weight:700;text-transform:uppercase;
           letter-spacing:0.06em;color:#666;margin:24px 0 10px;">
  Ran today &middot; 4
</h2>
```

### 5.3 Rating tile
A rounded swatch: tiny uppercase label over a big number. Background/foreground
come from the **value band** (§2). Used for Breeze / Precocity / any 0–100
rating; the same shape is reused as a date tile in the sales email.

```html
<table cellpadding="0" cellspacing="0" border="0" style="background:#cce5cc;border-radius:8px;">
  <tr><td style="padding:14px 18px;text-align:center;line-height:1;min-width:96px;">
    <div style="font-size:10px;color:#3c6c3c;font-weight:700;letter-spacing:0.1em;">BREEZE</div>
    <div style="font-size:28px;font-weight:700;color:#1f4a1f;margin-top:6px;">92.4</div>
  </td></tr>
</table>
```

Band thresholds: `≥90` strong-green · `≥70` high-green · `≥50` amber · `<50`
neutral · `None` paper (`—`). Date-tile variant: `padding:10px 14px`,
`min-width:54px`, value `26px`.

### 5.4 Badges (pills)
One recipe, three uses. `border-radius:10px`, bold, tight tracking.

```html
<!-- status: 11px -->
<span style="display:inline-block;background:#cce5cc;color:#1f4a1f;font-weight:700;
             font-size:11px;letter-spacing:0.04em;padding:2px 8px;border-radius:10px;">WON</span>

<!-- finishing position: 13px, optional "/ field" -->
<span style="display:inline-block;background:#fce99c;color:#7a5a00;font-weight:700;
             font-size:13px;padding:2px 10px;border-radius:10px;">1<span style="color:#888;font-weight:600;"> / 8</span></span>
```

Status kinds → colour: `won`→green, `placed`→amber, `ran`→neutral, else paper.
Position → colour: `1`→gold, `2`→silver, `3`→bronze, else neutral. Sales-state
badges (`ACTIVE`/`NEW`/`ONLINE`) reuse green/amber/slate.

### 5.5 Data tables (form / stats)
White card wrapper, uppercase grey `<th>`, numeric columns right-aligned,
`#efefe9` row rules. Small-sample rows are de-emphasised with
`color:#999;font-style:italic` and flagged in a footnote.

```html
<th style="padding:6px 8px;text-align:right;font-size:10px;color:#888;
           font-weight:700;letter-spacing:0.08em;text-transform:uppercase;">SR</th>
...
<td style="padding:6px 8px;font-size:13px;text-align:right;
           border-top:1px solid #efefe9;font-weight:600;">38%</td>
```

### 5.6 Empty state
Same white card, a single reassuring line — never a blank section.

```html
<div style="background:#fff;border:1px solid #e3e3de;border-radius:8px;padding:20px;">
  <p style="margin:0;color:#444;font-size:15px;font-weight:600;">No Results Today</p>
</div>
```

### 5.7 Footer
Small print in `#aaa`, `11px`, `line-height:1.5` — sources, definitions,
attachment filename, optional diagnostics line in `#c4c4c4`.

---

## 6. Silks (jockey colours)

Silks are the one image in the design and get special handling because email
clients are hostile to SVG and remote images.

- **Source:** Racing Post silk SVGs (viewBox `0 0 98.45 70.53`, ~**1.4 : 1**
  landscape).
- **Rasterised to PNG at send time** with `resvg-py`, on a **white
  background**, at **80 × 57 px** (2× for retina). Displayed at **56 × 40 px**.
- **Reason:** Gmail blocks remote SVG and clients cache/sanitise remote
  `<img src>`. A CID-attached PNG is the only thing that renders reliably
  across Gmail web/iOS, Apple Mail and Outlook. `resvg` is used over
  `cairosvg` because it ships static wheels (no system Cairo needed on the
  Windows cron host).
- **RP quirk:** silk SVGs declare `width/height` in `pt`, which resvg rejects;
  strip those attributes so it falls back to the viewBox + render size.
- **Referenced by CID:** the id is deterministic, `silk-<sha1(url)[:16]>`, so
  the template can reference `cid:` before the image is fetched/attached.

Display markup:

```html
<td style="padding:14px 0 8px 16px;vertical-align:middle;width:64px;">
  <img src="cid:silk-1a2b3c…" alt="silks" width="56" height="40"
       style="background:#fff;display:block;border-radius:4px;">
</td>
```

If a fetch/render fails the `<img>` simply falls back to its `alt` text — the
card must still read correctly without the silk (cards are laid out for
2 *or* 3 columns depending on whether a silk is present).

To replicate elsewhere: keep the **1.4:1 aspect, white backing, 56×40 display,
4px radius**, and attach as inline CID PNG rather than linking.

---

## 7. Iconography & glyphs

No icon font or image icons. Meaning is carried by:

- **Separators:** ` &middot; ` (`·`) between facts, ` | ` (`#bbb`) between
  clauses, `&times;` (`×`) in pedigree (sire × dam).
- **Country flags:** emoji flag glyph inline (sales email).
- **Chevrons:** `&rsaquo;` (`›`) on call-to-action links ("View sale ›").
- **Podium/status:** colour pills, not icons.

---

## 8. Email construction (delivery)

- Build with `email.message.EmailMessage`; set `Subject/From/To/Date/
  Message-ID`.
- `msg.set_content(text)` then `msg.add_alternative(html, subtype="html")`
  → `multipart/alternative`.
- Attach silks with `add_related(png, maintype="image", subtype="png",
  cid="<silk-…>")` against the **HTML part** (so they nest as
  `multipart/related` inside the HTML alternative).
- Send over SMTP with STARTTLS (Gmail app password in this project).

**Subject line conventions** — `Title — Ddd DD Mon YYYY (N horses)`:

```
Breeze-up entries — Wed 01 Jul 2026 (3 horses)
Breeze-up results — Wed 01 Jul 2026 (2 horses)
Breeze-up results — Wed 01 Jul 2026 · No Results Today
Sales catalogues — Wed 01 Jul 2026
```

Date in subjects uses `%a %d %b %Y`; the em dash `—` separates title from
date; the count (or a status phrase) goes in parentheses / after ` · `.

---

## 9. Rendering (Jinja2)

- `jinja2.Environment` with `PackageLoader`, `trim_blocks=True`,
  `lstrip_blocks=True`, and `select_autoescape` for `html/html.j2`.
- Reusable pieces are Jinja **macros** defined at the top of the template
  (`rating_tile`, `pos_badge`, `status_badge`, `stat_row`, `horse_card`, …).
  Replicate the components as macros so colour logic lives in one place.
- Colour-band selection lives *inside* the macro (`{% if value >= 90 %}…`),
  keeping call sites clean.

---

## 10. Plaintext companion

Every HTML email ships a matching monospace-friendly plaintext part built in
the same module (`_render_text`). Its conventions:

- Section headers wrapped in `═══ HEADER · N ═══`.
- Cards separated by a `─` × 60 divider line.
- Sub-facts indented 4 spaces; race/finish lines prefixed `► `.
- Tables are space-padded fixed-width columns; small-sample rows flagged `*`.
- Ends with the raw source URL per card.

Keep it — it's the accessible/again-fallback rendering and some clients show
it.

---

## Quick-start checklist to replicate the look

1. `<body>` `#f4f4f1`, `padding:24px`, the system font stack, ink `#1a1a1a`.
2. Centre a `max-width:920px` container.
3. Masthead: 22px/600 title + 13px `#666` "date · count" line.
4. Everything else is a **white `#fff` card**: `1px solid #e3e3de`, radius 8,
   `12px` gap.
5. Section headers: 13px/700 uppercase `#666`, `0.06em` tracking.
6. Use the **5 semantic swatch families** for any coloured tile/badge; greys
   for all other text.
7. Links `#1a5fb4`, no underline, weight 600.
8. Numbers → rating tiles (big 28px bold on a band-coloured rounded swatch).
9. States → 10px-radius pills.
10. Any image → inline CID PNG, white-backed, on a system font fallback.
11. Ship `multipart/alternative` with a plaintext twin.
</content>
</invoke>

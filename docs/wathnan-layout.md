# Report layout

Everything below is measured from the circulated report and encoded as constants
in [`wathnan/render.py`](../wathnan/render.py). Adjusting the layout means
changing a constant, not rewriting the renderer.

## Page

| | Value |
| --- | --- |
| Size | US Letter landscape, 792 × 612 pt |
| Left margin | 70.5 pt |
| Top margin, page 1 | 121.1 pt (clears the wordmark and silks) |
| Top margin, later pages | 72.5 pt |
| Bottom margin | 36 pt |
| Wordmark | 123.75 × 88.5 pt at (9, top − 97.5) |
| Silks | 111 × 78.75 pt at (679.5, top − 87.75) |

Branding is drawn on page one only; continuation pages carry the table alone,
as the source report does.

The wordmark is the official gold version from wathnan-racing.com — brand gold
`#B69E60` — rather than the black copy embedded in the circulated spreadsheet
export. A test (`test_logo_asset_is_the_official_brand_gold`) pins the colour
so a stray asset swap fails CI.

## Type

| Element | Font | Size |
| --- | --- | --- |
| Section heading | Roboto Condensed Bold | 12 pt |
| Column headings | Roboto Condensed Bold | 7 pt |
| Body cells | Roboto Condensed | 7 pt |
| Horse | Roboto Condensed Bold | 7 pt |
| Arabian race rows | the italic of the above | 7 pt |

The four faces are bundled in `wathnan/assets/fonts/`. If they are missing the
renderer falls back to the Helvetica family, which keeps the layout intact.

## Table

Header band `#9FC5E8`, 16.5 pt tall; body rows 21 pt where the content fits on
one line. Grid lines are 0.5 pt black. Cell padding is 3.7 pt left, 1.5 pt right.

| Column | Width (pt) | Alignment |
| --- | --- | --- |
| DATE | 26 | left |
| COURSE | 57 | left |
| RACE TYPE | 129 | left |
| DISTANCE | 34 | centre |
| UK TIME | 35 | centre |
| QATAR TIME | 41 | centre |
| HORSE | 78 | left |
| SIRE | 52 | left |
| DAM | 48 | left |
| TRAINER | 60 | left |
| JOCKEY | 51 | left |

Total table width 611 pt.

### Near-fit values

The source report is a spreadsheet export, so a value a shade wider than its
column simply overflows into the next one. ReportLab cannot overflow, so a
single-line value that misses by less than 5% is set very slightly smaller
instead of wrapping — that is what keeps `WOLVERHAMPTON` on one line. Anything
wider than that wraps, exactly as in the original. The threshold is
`MAX_SHRINK` in `render.py`.

## Grouping

Rows are one per runner. `wathnan.models.group_rows` decides which grouped cells
print:

* the **date** prints on the first row of each day;
* the **course** prints on the first row of each course within that day;
* **race type, distance and both times** print on the first row of each race.

Blank cells still carry their grid lines, so the table reads as one continuous
block.

## Section headings

Built by `render.build_sections`:

```
TOMORROW’S RUNNERS - FRIDAY 14TH AUGUST
UPDATED ENTRIES SATURDAY 15TH - WEDNESDAY 19TH AUGUST
```

Note the typographic apostrophe in the first heading, and that the second names
the weekday and ordinal at both ends of the window.

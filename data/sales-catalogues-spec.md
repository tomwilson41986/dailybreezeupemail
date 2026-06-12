# Spec: Thoroughbred Sales Catalogues Aggregator

Build a data pipeline that aggregates upcoming and currently-active thoroughbred
auction sales (and their lot-level catalogues) from 12 auction houses worldwide,
and exposes the result to the website (e.g. as a JSON feed, API endpoint, or
database tables the site renders). This replicates a proven production system;
follow the architecture below closely — the details encode hard-won fixes for
bot-blocking, messy date formats, and flaky sites.

## 1. Architecture overview

```
sources/*.py  (one adapter per auction house)
    └─ fetch(session, ref) -> list[RawSale]          # scrape the sale calendar
    └─ fetch_lots(raw, session) -> list[Lot]         # optional: published catalogue lots
            ↓
registry.py   (ordered list of sources; failures isolated per source)
            ↓
classify.py   (pure functions: exclusion filter, sale-type bucket, active flag)
            ↓
db (seen-ledger keyed on catalogue_id) → "New" flag
            ↓
output: grouped-by-country listing + lot-level rows
```

Key principles:

- **Per-source failure isolation.** Wrap every source's `fetch` in try/except;
  log the error, record `ERR:<ExceptionName>` in a per-source status dict, and
  continue. One broken site must never sink the whole run. Same for each
  catalogue's `fetch_lots`.
- **Pure parsers, fixture tests.** Every adapter splits into a `fetch_*`
  function (network) and a `parse_*` function (pure: HTML/JSON in, dataclasses
  out). Save a captured copy of each site's HTML/JSON as a test fixture and
  unit-test the parsers offline.
- **Bot-evasion via TLS impersonation.** Build the HTTP session with
  `curl_cffi.requests.Session(impersonate="chrome124")`, falling back to plain
  `requests` if curl_cffi is unavailable. Several of these sites (Fastly /
  Cloudflare fronted) block datacentre IPs with default TLS fingerprints.
  Set a real Chrome User-Agent and Accept/Accept-Language headers too.
- **Retries.** Wrap GETs with tenacity: 3 attempts, exponential backoff
  (min 1s, max 8s). Timeout 30s.

## 2. Data model

```python
@dataclass
class RawSale:                       # one calendar entry from one house
    house: str                       # e.g. "Tattersalls", "Goffs"
    country: str                     # "UK","IRE","FR","DE","US","AUS","NZ"
    name: str                        # sale name as published
    start_date: date | None
    end_date: date | None            # None for single-day sales
    url: str                         # link to the sale / catalogue page
    online: bool = False             # online/digital sale
    description: str = ""            # free text, used by the exclusion filter
    status_hint: str = ""            # source-side status, e.g. "catalogue available", "live"
    type_hint: str = ""              # source-side category, if the site has one
    source_key: str = ""             # which adapter produced it
    catalogue_ref: str = ""          # source-internal id used by fetch_lots

@dataclass
class Lot:                           # one horse in a published catalogue
    lot_no: str
    horse_name: str = ""             # "" when unnamed (foals/yearlings often are)
    sex: str = ""                    # Colt/Filly/Gelding/Mare
    colour: str = ""                 # Bay, Chestnut, Grey...
    sire: str = ""
    dam: str = ""
    dam_sire: str = ""
    vendor: str = ""                 # consignor

@dataclass
class Catalogue:                     # RawSale enriched for display
    raw: RawSale
    sale_type: str                   # see §5
    is_new: bool                     # first time we've ever seen this sale
    is_active: bool                  # see §6
    status_label: str                # "Active · New", "Upcoming", etc.
    first_seen: date | None
```

**Stable identity for dedup and new-detection** — `catalogue_id` property:
`slug(house) + "|" + slug(name) + "|" + YYYY-MM of start_date` (or `"nd"` if
undated). Slug = NFKD-normalised ASCII, lower-case, non-alnum runs collapsed to
`-`. Keying on start *month* rather than exact day means the same sale tracks
across days even when a source nudges the date, while October Book 1 vs Book 2
stay distinct. Dedup across sources on this id (first source wins).

## 3. The 12 source adapters

Country codes & display order: UK, IRE, FR, DE, US, AUS, NZ.

| Key | House (country) | Calendar endpoint | Format | Lots endpoint |
|---|---|---|---|---|
| `tattersalls` | Tattersalls (UK) + Tattersalls Ireland (IRE) | `https://secure.tattersalls.com/4DCGI/Sale/SaleDates?site=NMT` and `https://secure.tattersalls.ie/4DCGI/Sale/SaleDates` | HTML `.sale-card` blocks | `https://{host}/4DCGI/Sale/{code}` HTML table |
| `tattersalls_online` | Tattersalls Online (UK, online) | `https://www.tattersallsonline.com/` | HTML | 4D listing as above |
| `goffs` | Goffs + Goffs UK (IRE/UK) | `https://www.goffs.com/upcoming-sales` | HTML | HTML |
| `arqana` | Arqana (FR) | `https://www.arqana.com/catalogues_results.html` | HTML | HTML |
| `bbag` | BBAG (DE) | `https://bbag-sales.de/events{YYYY}~en_GB` | HTML | `https://backend.3forone.auction/api/v1/bbag-auction/auction/{slug}/auctionlots` JSON |
| `keeneland` | Keeneland (US) | `https://www.keeneland.com/sales/` | HTML | `https://www.keeneland.com/json/sale_api/get/catalog/{sale_id}` JSON |
| `fasigtipton` | Fasig-Tipton (US) | `https://www.fasigtipton.com/calendar/{YYYY}` | HTML | `https://www.fasigtipton.com/django/api/sales/?sale_identifier={code}` then `/django/api/horses/?sale={sale_id}` JSON |
| `obs` | OBS (US) | `https://obssales.com/` | HTML | `https://obssales.com/wp-json/obs-catalog-wp-plugin/v1/horse-sales/{sale_id}` JSON |
| `inglis` | Inglis (AUS) | `https://inglis.com.au/calendar` | HTML | HTML |
| `magicmillions` | Magic Millions (AUS) | `https://www.magicmillions.com.au/sales/?upcoming=true` | HTML | HTML |
| `nzb` | NZB (NZ) | `https://www.nzb.co.nz/sales/upcoming` | HTML | HTML |
| `gavelhouse` | Gavelhouse (NZ, online) | `https://gavelhouse.co.nz/api/currentcatalogue` | JSON | `https://gavelhouse.co.nz/api/lots?catalogue={id}&detail=2` JSON |

Adapter notes:

- **Tattersalls**: each `.sale-card` carries the name (`.sale-card__heading a`),
  date text (`.sale-card__meta-item-text`), and a status CSS class
  (`sale-card--status-entries-open|entries-closed|catalogue-available`) — use
  that as `status_hint`. The internal sale code (e.g. `JUL26`) is in the
  heading href (`/4DCGI/Sale/{code}`); store it as `catalogue_ref`. To fetch
  lots, first GET `{base}/Main/Overview` to seed the 4D session cookie, then
  GET `{base}` for the lot table. Lot rows: `td.lot a.ll` = lot no,
  `td.tdh a.hn` = name, `span.small` labels `BY`/`EX` precede sire/dam in tail
  text, a "2023 Ch.F."-style token gives colour+sex, vendor is the `td` after
  `td.col2type`.
- **UK/IRE colour+sex tokens** like `B.F.` / `Ch.C`: trailing letter is sex
  (C/F/G/H/M → Colt/Filly/Gelding/Horse/Mare); leading part is colour
  (B/Ch/Gr/Br/Bl/Ro/Dkb → Bay/Chestnut/Grey/Brown/Black/Roan/Dark Bay).
- **JSON APIs returning 200 + empty body** mean "catalogue not published yet" —
  treat as no lots, not an error.
- Mark Tattersalls Online and Gavelhouse sales `online=True`; Gavelhouse is a
  rolling auction that may have no dates — see §6.

## 4. Date parsing (do not skimp here)

The houses publish a dozen formats: "6 – 8 October 2026", "Mon 2 Sep",
"30 January - 4 February", "October 6-8", "1st - 3rd Dec", with or without
years. Write one tolerant `parse_date_range(text, ref, dayfirst=True) ->
(start, end)`:

- Normalise: lower-case; map en/em dashes, `&`, "to", "and" → `-`; strip
  weekday names and ordinal suffixes; strip "Book N"/"Day N"/"Part N" prefixes.
- Extract an explicit year (`20\d\d`) if present, remove it from the string.
- Tokenise into month words and 1–2 digit day numbers; pair days with months
  respecting day-first (UK/EU/AUS/NZ) vs month-first (`dayfirst=False` for US
  sources, and whenever the string *opens* with a month word).
- First (day, month) pair = start; last = end. If end month < start month, the
  range crosses a year boundary → end year +1.
- **Missing year inference**: assume `ref.year`; if the resulting end date is
  more than 60 days in the past relative to `ref`, roll both forward one year.
  The 60-day grace keeps a just-finished sale in the current year.
- Return `(None, None)` if no month word found; `end=None` when end == start.

## 5. Classification (pure functions)

**Exclusion filter** — drop jumps / National Hunt / store / non-thoroughbred
sales. Case-insensitive regex over `name + description + type_hint`:
`national hunt`, `\bn\.?h\.?\b`, `\bjump(s|ing)?\b`, `steeple`, `\bstore(s)?\b`,
`point[\s-]?to[\s-]?point`, `\bp2p\b`, `\baqps\b`, `arab`, `\bpony\b|\bponies\b`,
`trotting|harness|standardbred`, `land rover`. Plus a named blocklist matched
as substrings of the sale name for NH sales whose listings carry no keyword:
`derby sale`, `land rover`, `arkle`, `sportsmans`.

**Sale type** — bucket into one of six types, first matching rule wins
(most-specific first), over `name + description`; trust a source `type_hint`
only when it names one of the buckets:

| Type | Icon | Patterns |
|---|---|---|
| Breeze Up | ⏱️ | `breeze[\s-]?up`, `ready[\s-]?to[\s-]?run`, `\brtr\b` |
| HIT | 🏇 | `horses? in training`, `horses? of racing age`, `\bhit\b`, `\bhra\b`, `horses? of all ages`, `racing age` |
| Foal / Weanling | 🍼 | `weanling`, `\bfoal` |
| Broodmare | ♀️ | `broodmare`, `breeding stock`, `\bmares?\b`, `in[\s-]?foal` |
| Yearling | 🐎 | `yearling` |
| Mixed (default) | 🔀 | `\bmixed\b`, `breeding &/and` |

## 6. Active / Upcoming / New logic

- **Active**: from `ACTIVE_LEAD_DAYS` (default **2**) before the sale's first
  day through its last day, inclusive. Undated sales count as active when
  `status_hint` is `live` / `bidding-open` / `open` (rolling online auctions).
- **In scope (Upcoming)**: not excluded, not finished (`end >= today`), and
  starting within `HORIZON_DAYS` (default **30**) of today. Undated sales are
  kept.
- **New**: first run on which the `catalogue_id` appears. Persist a
  seen-ledger:

```sql
CREATE TABLE IF NOT EXISTS seen_catalogue (
    catalogue_id TEXT PRIMARY KEY,
    house TEXT NOT NULL, country TEXT NOT NULL, name TEXT NOT NULL,
    start_date TEXT, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL
);
```

  Upsert on every run: insert with `first_seen = today` first time, otherwise
  bump `last_seen` only. `is_new = (first_seen is None or first_seen == today)`.
  Also keep a `run_log` table (run_date, started_at, finished_at, status,
  summary_json) for diagnostics.

- **Status label** for display: "Active" and/or "New" joined with " · ";
  otherwise the title-cased source `status_hint`, falling back to "Upcoming".

## 7. Presentation / output

Group by country in fixed order (UK 🇬🇧, IRE 🇮🇪, FR 🇫🇷, DE 🇩🇪, US 🇺🇸, AUS 🇦🇺,
NZ 🇳🇿; unknown codes last under "Other" — never silently drop a sale). Within
each country sort: Active first, then New, then by start date (undated last),
then name. Each row: type icon, sale name, human date span ("6 – 8 Oct 2026",
"2 Sep 2026", "Date TBC"), status label, link to the sale page plus a link to
the house homepage (keep a `HOUSE_WEBSITE` dict).

Lot-level export: one row per lot repeating the sale columns
(Country, House, Sale Name, Type, Start, End, Online, New, Active, Status,
Sale URL, House URL | Lot No, Horse Name, Sex, Colour, Sire, Dam, Dam Sire,
Vendor). A sale whose catalogue isn't published yet still gets one summary row
with blank lot columns.

For the website, replace the original email step with whatever fits: write
`catalogues` + `lots_by_catalogue_id` to the site's database, or serve them as
JSON, e.g.:

```json
{
  "generated_at": "...",
  "catalogues": [{ "id": "...", "house": "...", "country": "UK",
    "name": "...", "sale_type": "Yearling", "start_date": "2026-10-06",
    "end_date": "2026-10-08", "is_active": false, "is_new": true,
    "status": "New", "url": "...", "house_url": "...", "online": false,
    "lots": [{ "lot_no": "1", "horse_name": "", "sex": "Colt",
      "colour": "Bay", "sire": "...", "dam": "...", "dam_sire": "...",
      "vendor": "..." }] }],
  "diagnostics": { "source_status": "tattersalls=14, goffs=ERR:HTTPError, ..." }
}
```

## 8. Scheduling & config

Run daily (original: GitHub Actions cron 06:00 UTC, `TZ=Europe/London`).
"Today" is computed in Europe/London. Support `--date YYYY-MM-DD` and
`--dry-run` (render output to files, don't publish). If state can't live in a
real database, persist the SQLite file across CI runs with `actions/cache`
using a unique key per run + a `restore-keys` prefix so each run saves a fresh
snapshot and restores the latest.

Config via environment (pydantic-settings or equivalent): `ACTIVE_LEAD_DAYS=2`,
`HORIZON_DAYS=30`, `NOTIFY_ON_EMPTY=false` (skip publishing when nothing is
New/Active), plus whatever credentials the output channel needs.

Dependencies: `curl_cffi`, `requests`, `tenacity`, `lxml` (+cssselect),
`pydantic-settings`. Python 3.12.

## 9. Suggested build order

1. `models.py` (dataclasses, countries, sale types, `catalogue_id`) and
   `base.py` (session, retried GETs, `parse_date_range`, `split_sex_colour`) —
   with unit tests for the date parser edge cases in §4.
2. `classify.py` (exclusion, type rules, active/status) — pure-function tests.
3. The seen-ledger + orchestrator skeleton with per-source isolation.
4. Source adapters one at a time, easiest first (Gavelhouse and the JSON APIs,
   then Tattersalls, then the HTML-only sites). Capture a fixture for each and
   test the parser offline.
5. The output layer for the website, then the scheduler.

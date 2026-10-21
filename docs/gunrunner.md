# Gun Runner Mare Prospects (`gunrunner-weekly`)

Friday email. Every filly and mare catalogued worldwide for a sale in the next
ten weeks, scored out of 100 as a Gun Runner mate. Attached: the PDF (cover,
rules, ranked list, one page per prospect) and two CSVs (the prospects; every
filly and mare scored, with why each one missed).

## Pipeline

1. **Lots** (`collect.py`): the Sales Catalogues adapters (`salescatalogues.daily.collect_raw`,
   `build_catalogues`, `lots.collect_lots`) with a 70-day horizon. Fillies and mares
   only, withdrawn lots out, one row per horse when two sales catalogue her. Year of
   birth from the house, else from the sale type (foal, yearling, breeze-up; southern
   hemisphere aware).
2. **Her record** (`enrich.py`), best source first:
   - the desk's sale data on blandfordbloodstock.tech: AuctionEdge (peak E, AEI, best
     win, Thoro-Graph, R2 Rating, first cover, produce) for the US breeding-stock sales,
     Timeform for the HIT sales. Sales listed in `GUNRUNNER_WEBSITE_SALES`;
   - Equibase through parse.bot (US): runs, E figures, grades, surface;
   - the backend results table (`/api/breeding/family?dam=<her name>`): Timeform-scale
     best, black type, her produce;
   - the worldwide file (`worldwide.py`, 2014+ crops, every country): surfaces and
     winning trips.
3. **Family** (`family.py`): dam, 2nd dam, 3rd dam and their produce, from the backend
   family page, the worldwide file and (US, within budget) Equibase.
4. **Forecast distance fit** (`forecast.py`, unraced only): the site's aptitude blend.
   Sire's winners' trips (n/(n+40)) half; dam's side half: her produce (n/(n+8)), her
   own racing (1/5), her sire as a broodmare sire (n/(n+40)), the rest all winners.
   Fit = share at 8-10f. All winners: 24%.
5. **Score** (`score.py`). Rules in the module docstring and on page 2 of the PDF.

## Dirt

Worldwide file: AW is dirt when the best AW run's going is a dirt going (FT, SY, MY, WF,
SL), or she was foaled where AW is dirt (USA, Canada, Japan, South America, Saudi
Arabia). British, Irish, French and Australian AW is synthetic. Equibase: a run is turf
when the race name says so or the track is turf-only.

- US: raced, her own form mostly on dirt; unraced, dirt form under the dam.
- Europe and Australasia: dirt form anywhere to the 3rd dam.

## Status

Foals, yearlings, 2yos, fillies in training and maidens: all. Covered mares: first foal
only, and only by Into Mischief, Not This Time, Gun Runner, Curlin, Vekoma, Epicenter or
Gunite (`config.COVER_SIRES`). Any produce on record makes her experienced. A covered
mare with no produce on record counts as a first foal up to age 6. Gun Runner's daughters
are out; Candy Ride-line sires lose 5.

## Caches and budget

`data/gunrunner/cache.sqlite` (Actions cache): backend family pages (four to six weeks),
Equibase answers (for good), website lot files, HRN silks (60 days), and the ledger of
horses already reported (the "new this week" flag). The first run fetches every dam's
family page (about 8,000, an hour at the backend's pace); after that only new dams.
The Wednesday warm run does that work so Friday's is quick.

Equibase spends at most `GUNRUNNER_EQUIBASE_CREDITS` (default 1,500) a run, the likeliest
prospects first, and stops at 50 credits left. A horse is paid for once.

## Running it

```bash
pip install -e ".[report]" && python -m playwright install chromium
gunrunner-weekly --dry-run          # writes data/gunrunner/out/<date>/
gunrunner-weekly --warm             # caches only
```

Secrets: `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `EMAIL_FROM` (shared), `PARSE_BOT_API_KEY`,
`GUNRUNNER_EMAIL_TO` (optional; default racingsquared@gmail.com, greg@p2bloodstock.com).

## Gaps

- Online sales (GoffsGo, ThoroughBid, Arqana online, BBAG online, Inglis Digital, Magic
  Millions Digital) come through once each catalogue is published, usually a week or so
  before bidding. Part-shares and breeding rights are skipped.
- Tattersalls December Mares and Yearlings appear once the catalogues are published.
- Equibase has no surface or distance: surface from the race name, trip from AuctionEdge
  or the worldwide file.
- The worldwide file starts with the 2014 crop; older dams come from the backend
  results table, which is strongest for Britain and Ireland.

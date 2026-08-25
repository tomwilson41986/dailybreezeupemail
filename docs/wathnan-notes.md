# Wathnan runners report — working notes

Builds the daily **TOMORROW'S RUNNERS / UPDATED ENTRIES** PDF and emails it at
08:00 UK. `README.md` explains how to use it; this file is the context a new
session needs to change it safely — mostly things that took real digging to
find and that are expensive to rediscover.

```
wathnan-daily                     # today's report -> output/
wathnan-daily --no-browser -v     # what a debugging run usually looks like
pytest tests/wathnan              # 158 tests, all offline, ~2s
```

## The one thing to understand first

Two of the five requested sources refuse a plain request from a cloud IP —
Racing Post via Signal Sciences (HTTP 406), Equibase via Imperva (403).

**Racing Post is a TLS/HTTP-2 fingerprint check, not an IP block**, and
`curl_cffi` impersonating Chrome walks straight through it. Verified from this
very container: `impersonate="chrome110"` returns the full 489 KB owner entries
page, and the existing `_from_state()` walker parses 92 runners out of its
`__NEXT_DATA__` without modification. Newer impersonations (`chrome124`,
`chrome120`) were reset by the egress proxy — their post-quantum ClientHello is
the likely cause — so the version is worth making configurable.
This is wired in. Note the adapter runs **both** feeds and merges: the owner
page is the authoritative entry list and reaches furthest ahead, but it carries
no pedigree and names a trainer or jockey only once a race is declared. Running
it *instead of* the sweep silently blanks the SIRE, DAM and TRAINER columns —
that regression was caught during the migration. Neither feed alone is the
report.

**Equibase is tougher** — Imperva serves a JS challenge that no impersonation
tested got past. It needs the fallback.

The fallback is **Sporting Life's public racecard API** (`src/wathnan/sources/
sportinglife.py`) — the feed behind Sky Bet. No key, no bot wall, and it carries
the same declarations with the **owner named on every ride**. Both blocked
adapters use it automatically, split by jurisdiction so they cannot report the
same race twice:

- `racingpost.py` → sweeps everything **except** North America
- `equibase.py` → sweeps **only** North America

Do not "fix" the blocked adapters by deleting them, and do not let both
fallbacks cover the same country.

## Feed quirks that will bite you

Each of these caused a visible bug in a shipped report. They are all fixed, with
tests — this is why the code looks the way it does.

**Sporting Life**
- Post times are **UTC**, for every track. Convert per race day or French cards
  land an hour out. (`_race()` → `to_uk_time(..., tz=UTC)`)
- Trainers are abbreviated (`W J Haggas`), jockeys usually are not.
- No country suffix on horse names, ever.
- **US cards publish only ~a day ahead.** A Grade 1 runner can be in yesterday's
  report and gone from today's. The horse endpoint still lists it under
  `future_entries`, which is what `src/wathnan/data/roster.json` + `_roster_races()`
  exist for. Do not remove that path; it is not redundant.

**France Galop**
- Public pages cover **today and tomorrow only**. The owner-area URL the client
  gave is behind Microsoft SSO — set `FRANCE_GALOP_USER`/`_PASSWORD` to use it.
- Horse cell carries a tail: `FIRE BULLET IRE M.PS. 2 a.` A supplementary entry
  adds `... (Sup.)` **after** the tail, which defeated the anchored strip and
  split one horse into two rows.
- Riders carry a licensing country: `JAMES WILLIAM DOYLE (GBR)`.
- Country code appears only on **foreign-bred** horses → no code means `(FR)`.
- Breed comes from the horse's own code (`F.AR.` = Arabian), not the URL.

**Deutscher Galopp**
- The calendar page embeds the whole next fortnight; one fetch gets every race.
- Pedigree, owner, trainer and rider live in a **tooltip `title` attribute**
  (`Abstammung: v.SIRE - DAM`), not in the table cells.
- No code means `(GER)`, same convention as France.

**QREC**
- Clean JSON API. `POST /token/generate` then
  `race/data?pageaction=jsonracetab&raceid=…`. The API key and secret in
  `qrec.py` are the ones QREC publishes in its own browser bundle — public
  client credentials, overridable via `QREC_API_KEY`/`_SECRET`.
- Season runs roughly October–May, so **zero rows in summer is correct**.

## Name and suffix reconciliation

Feeds disagree about names, so everything is resolved **once, after
de-duplication** (`src/wathnan/enrich.py`), never per-source.

- `data/people.json` — canonical spellings. A variant resolves when it shares a
  **surname and first initial** with exactly one entry, so new abbreviations of
  a known person need no edit. Ambiguity is deliberately left alone rather than
  guessed. Partnerships need explicit aliases.
- `data/horses.json` — country of foaling, for the `(IRE)` suffix.
- `data/roster.json` — Sporting Life horse ids, for the late-card recovery.

The last two **grow themselves** on a `--learn-suffixes` run. Unknown suffixes
are looked up from irishracing.com, which links runners as
`/horse/Old-Is-Gold-IRE/1184426` — **GB and Ireland only**, so a French or US
horse arriving via the GB feed may print bare until added.

**Never invent a person's full name.** If a feed gives `Y Lachhab` and the real
name is not verifiable, leave it. A wrong name in a client-facing report is
worse than an abbreviated one.

## The renderer

`render.py` reproduces the client's spreadsheet export measurement for
measurement — every constant in `wathnan-layout.md` was taken off the original PDF.
Do not casually adjust widths, padding or the `#9FC5E8` header fill; the golden
test in `test_render.py` asserts column geometry, fill colour and bold/italic
runs against the circulated 14th August report.

Conventions worth knowing: horses bold, **Arabian races italic throughout**,
date printed once per day, course once per course, race details once per race,
`TBC` for an undeclared ride, branding on page one only.

`MAX_SHRINK` lets a near-fit single-line value shrink slightly rather than wrap
— that is what keeps `WOLVERHAMPTON` on one line, matching the original's
spreadsheet overflow.

## Scheduling

GitHub's scheduler is UTC-only, so 08:00 in London is 07:00 UTC for half the
year and 08:00 UTC for the other half. **Both hours are booked** and a cheap
shell gate keeps whichever slot is 08:00 locally today, stopping the other
before it spends five minutes installing.

The gate decides from **which cron fired** (`github.event.schedule`), never from
the wall clock. GitHub's scheduler is best-effort and routinely starts 40–60
minutes late — occasionally hours. A run that asked "is it 08:00 now?" would
answer no and silently send nothing on exactly the mornings it was already
running late. Asking "am I the slot that is 08:00 in London today?" is immune to
that. Do not reintroduce a clock check here; `--only-at` remains in the CLI only
for standalone cron, where the scheduler is punctual.

Scheduled workflows only run from the **default branch**, and GitHub disables
them after 60 days without commits.

## Working on this

- **Tests are entirely offline.** Fixtures in `tests/wathnan/fixtures/` are real pages
  captured from the live sites. Add a fixture rather than reaching for the
  network in a test.
- **Every source failure is non-fatal by design.** A dead feed produces a
  footnote on the PDF, not a failed run — an empty section must never be
  mistaken for a quiet day.
- **Verify a surprising result before shipping it.** "No runners tomorrow" has
  been genuine once and a silent feed regression once. Check the day's meetings
  directly before believing an empty table.
- Snapshots land in `snapshots/` and are reused for an hour, so re-runs are
  cheap and a parse bug can be debugged against the exact page the run saw.
- Adding a source: subclass `Source`, return `Race` objects from `fetch()`,
  register it in `src/wathnan/sources/__init__.py`. De-duplication merges it with the rest.

## Known gaps

- Racing Post is reachable via `curl_cffi` and the adapter now uses it, running
  alongside the racecard sweep rather than instead of it — see above.
- Equibase remains unreachable from a cloud IP; the fallback is the only route.
- Suffix lookup does not cover French or American courses.
- QREC pedigree needs one extra request per horse; it is best-effort and fails
  quietly.
- `--learn-suffixes` writes into the package directory, so it is deliberately
  **not** enabled in CI — the registries grow when a human runs it locally.
- `mypy --strict` reports ~80 findings here, in the same spirit as the ~40 in
  `dailybreezeup`. Nothing in CI enforces it; `ruff check` is clean.

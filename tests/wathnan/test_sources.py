"""Parser tests driven by pages captured from the live sites."""

import datetime as dt
import json
from dataclasses import replace

import pytest
from bs4 import BeautifulSoup

from wathnan.config import build_config
from wathnan.models import Breed, Status
from wathnan.sources import SOURCES
from wathnan.sources.deutscher_galopp import DeutscherGaloppSource
from wathnan.sources.equibase import EquibaseSource
from wathnan.sources.france_galop import FranceGalopSource
from wathnan.sources.qrec import QrecSource, _runner_rows
from wathnan.sources.racingpost import RacingPostSource, _group_records
from wathnan.sources.tables import Column, find_tables, rows, split_pedigree


@pytest.fixture
def wathnan_config():
    return build_config(today=dt.date(2026, 8, 18))


@pytest.fixture
def open_config(wathnan_config):
    """Matches any owner, so a fixture without a Wathnan runner still exercises
    the row parsing."""
    return replace(wathnan_config, owner_aliases=("",))


# -- owner matching -------------------------------------------------------------
@pytest.mark.parametrize("owner,expected", [
    ("WATHNAN RACING", True),
    ("Wathnan Racing", True),
    ("Mr Wathnan Racing Ltd", True),
    ("H.E. Wathnan", True),
    ("Al Wathnan Racing", True),
    ("Godolphin", False),
    ("", False),
    (None, False),
])
def test_owner_matching(wathnan_config, owner, expected):
    assert QrecSource(wathnan_config).is_wathnan(owner) is expected


def test_every_source_is_registered():
    assert set(SOURCES) == {"racingpost", "deutscher_galopp", "france_galop",
                            "equibase", "qrec", "sportinglife"}
    for name, source in SOURCES.items():
        assert source.name == name and source.label and source.home


def test_the_default_run_uses_the_five_primary_sources(wathnan_config):
    # sportinglife is the fallback inside racingpost, not a sixth default feed.
    assert "sportinglife" not in wathnan_config.sources
    assert len(wathnan_config.sources) == 5


# -- France Galop ---------------------------------------------------------------
@pytest.fixture
def france_galop_page(fixtures):
    return BeautifulSoup(
        (fixtures / "france_galop_race_arabian.html").read_text(encoding="utf-8"), "lxml")


def test_france_galop_finds_the_wathnan_runner(wathnan_config, france_galop_page):
    runners, breeds = FranceGalopSource(wathnan_config)._wathnan_runners(france_galop_page)
    assert len(runners) == 1
    runner = runners[0]
    assert runner.horse == "DABIDA (FR)"
    assert (runner.sire, runner.dam) == ("Divamer", "Adiba")
    assert runner.trainer == "A. de Mieulle"
    assert runner.jockey == "Maxime Guyon"
    assert breeds == {"AR"}


def test_france_galop_reads_the_race_header(wathnan_config, france_galop_page):
    from wathnan.sources.france_galop import _conditions_category, _header
    header = _header(france_galop_page)
    assert header["date"] == dt.date(2026, 8, 19)
    assert header["time"] == dt.time(20, 0)
    assert header["course"] == "LA TESTE-BASSIN ARCACHON"
    assert "GROUPE III PA" in _conditions_category(france_galop_page)


def test_france_galop_builds_an_arabian_race(wathnan_config, france_galop_page, monkeypatch):
    source = FranceGalopSource(wathnan_config)
    monkeypatch.setattr(source, "_race_from_page", source._race_from_page)

    class _Stub:
        def get(self, url, **_):
            return str(france_galop_page)

    race = source._race_from_page(_Stub(), "https://example.invalid/race")
    assert race is not None
    assert race.breed is Breed.ARABIAN
    assert race.date == dt.date(2026, 8, 19)
    assert race.distance_furlongs == 9.5
    # 20h00 in Paris is 7pm in the UK.
    assert race.off_time_uk == dt.time(19, 0)
    assert race.race_type.endswith("Group 3 PA")
    assert race.status is Status.DECLARED


# -- Deutscher Galopp -----------------------------------------------------------
@pytest.fixture
def deutscher_galopp_page(fixtures):
    return BeautifulSoup(
        (fixtures / "deutscher_galopp_race.html").read_text(encoding="utf-8"), "lxml")


def test_deutscher_galopp_reads_the_entry_table(open_config, deutscher_galopp_page):
    runners = list(DeutscherGaloppSource(open_config)._wathnan_runners(deutscher_galopp_page))
    assert runners, "no runners parsed from the entry table"
    first = runners[0]
    assert first.horse.isupper() and first.horse.endswith(")")
    assert first.sire and "(" not in first.sire     # country codes are stripped
    assert first.trainer and first.trainer != first.trainer.upper()


def test_deutscher_galopp_ignores_other_owners(wathnan_config, deutscher_galopp_page):
    assert not list(DeutscherGaloppSource(wathnan_config)
                    ._wathnan_runners(deutscher_galopp_page))


def test_deutscher_galopp_labels_race_categories():
    from wathnan.sources.deutscher_galopp import _race_type
    assert _race_type("Grosser Preis", "Gruppe III") == "Grosser Preis Group 3"
    assert _race_type("", "Ausgleich III") == "Handicap (Ausgleich III)"
    assert _race_type("BNN Trophy", "Listenrennen") == "BNN Trophy (Listed Race)"


# -- QREC -----------------------------------------------------------------------
def test_qrec_runner_rows(fixtures):
    payload = json.loads((fixtures / "qrec_racetab.json").read_text(encoding="utf-8"))
    runner_rows = _runner_rows(payload["data"])
    assert len(runner_rows) > 5
    assert {"horseName", "ownerName", "trainerName", "jockeyName"} <= set(runner_rows[0])


def test_qrec_maps_a_runner(open_config, fixtures):
    payload = json.loads((fixtures / "qrec_racetab.json").read_text(encoding="utf-8"))
    source = QrecSource(open_config)
    runners = list(source._wathnan_runners(_NoFetch(), "token", payload["data"], {}))
    assert runners[0].horse == "ESTITHMAR (FR)"
    assert runners[0].trainer == "Jihad El Ahmad"
    assert runners[0].jockey == "Alberto Sanna"


def test_qrec_strips_a_jockey_claim():
    from wathnan.sources.qrec import _clean_jockey
    assert _clean_jockey("Salman Fahad Al-Hajri* (-2.5kg)") == "Salman Fahad Al-Hajri"


def test_qrec_detects_arabian_races():
    from wathnan.sources.qrec import ARABIAN_HINT
    assert ARABIAN_HINT.search("LOCAL PUREBRED ARABIAN MAIDEN PLATE (Class 6)")
    assert not ARABIAN_HINT.search("THOROUGHBRED HANDICAP 45-65 (Class 6)")


class _NoFetch:
    """QREC pedigree lookups are optional; this stands in for the fetcher."""

    def get_json(self, *_, **__):
        raise RuntimeError("no network in tests")


# -- header driven tables -------------------------------------------------------
TABLE = """
<table>
  <thead><tr><th>Date</th><th>Track</th><th>Horse</th><th>Trainer</th><th>Jockey</th></tr></thead>
  <tbody>
    <tr><td>08/19/2026</td><td>Saratoga</td><td>Wathnan Star</td>
        <td>C Brown</td><td>I Ortiz</td></tr>
    <tr><td></td><td></td><td>Second Runner</td><td>C Brown</td><td>J Rosario</td></tr>
  </tbody>
</table>
"""

EQUIBASE_COLUMNS = (Column("date", "date", required=True),
                    Column("course", "track", required=True),
                    Column("horse", "horse", required=True),
                    Column("trainer", "trainer"), Column("jockey", "jockey"))


def test_header_driven_table_reads_and_fills_forward():
    soup = BeautifulSoup(TABLE, "lxml")
    table, mapping = next(find_tables(soup, EQUIBASE_COLUMNS))
    records = list(rows(table, mapping))
    assert [record["horse"] for record in records] == ["Wathnan Star", "Second Runner"]
    # The blank date and track carry down from the row above.
    assert records[1]["date"] == "08/19/2026"
    assert records[1]["course"] == "Saratoga"


def test_tables_without_the_required_columns_are_skipped():
    soup = BeautifulSoup("<table><thead><tr><th>Foo</th></tr></thead>"
                         "<tbody><tr><td>1</td></tr></tbody></table>", "lxml")
    assert not list(find_tables(soup, EQUIBASE_COLUMNS))


@pytest.mark.parametrize("value,expected", [
    ("Kingman - Ventoux", ("Kingman", "Ventoux")),
    ("Kingman (Ventoux)", ("Kingman", "Ventoux")),
    ("Kingman", ("Kingman", "")),
    ("", ("", "")),
])
def test_split_pedigree(value, expected):
    assert split_pedigree(value) == expected


# -- Equibase / Racing Post -----------------------------------------------------
def test_equibase_parses_us_dates_and_spelled_out_distances(wathnan_config):
    from wathnan.sources.equibase import _parse_date
    assert _parse_date("08/19/2026") == dt.date(2026, 8, 19)
    assert _parse_date("August 19, 2026") == dt.date(2026, 8, 19)
    assert _parse_date("nonsense") is None


def test_equibase_detects_a_challenge_page():
    from wathnan.sources.equibase import _looks_blocked
    assert _looks_blocked("<title>Pardon Our Interruption</title>")
    assert not _looks_blocked("<table><tr><th>Date</th></tr></table>")


def test_racingpost_detects_a_waf_block():
    from wathnan.sources.racingpost import _looks_blocked
    assert _looks_blocked("origin: 3x33--F_sigsci_waf msg: Not Acceptable")
    assert not _looks_blocked("<html><table><th>Horse</th></table></html>")


def test_racingpost_reads_entries_out_of_embedded_state(wathnan_config):
    body = """<script>window.__PRELOADED_STATE__ = {"entries":[
      {"raceDate":"2026-08-19","courseName":"Yarmouth","raceName":"Class 5 Handicap",
       "distance":"5f","raceTime":"16:25","horseName":"Creative Queen","sireName":"Mitole",
       "damName":"Vigui's Heart","trainerName":"William Haggas","jockeyName":"Cieren Fallon",
       "ownerName":"Wathnan Racing"},
      {"raceDate":"2026-08-19","courseName":"Yarmouth","raceName":"Class 5 Handicap",
       "distance":"5f","raceTime":"16:25","horseName":"Someone Else","trainerName":"X",
       "ownerName":"Godolphin"}]};</script>"""
    records = list(RacingPostSource(wathnan_config)._from_state(body))
    assert len(records) == 1
    races = list(_group_records(records, "https://example.invalid", "racingpost"))
    assert len(races) == 1
    assert races[0].course == "YARMOUTH"
    assert races[0].off_time_uk == dt.time(16, 25)
    assert races[0].distance_furlongs == 5.0
    assert races[0].runners[0].horse == "CREATIVE QUEEN"
    assert races[0].runners[0].dam == "Vigui's Heart"


def test_racingpost_reads_the_race_title_off_the_live_owner_page(wathnan_config, fixtures):
    """The owner page ships the title as ``raceInstanceTitle``.

    Reports for the first week of September printed an empty RACE cell for
    every North American entry. GB rows looked fine only because the Sporting
    Life racecard filled the name in on merge; a US card is not published until
    the day, so the Racing Post row stood alone -- and the walker did not know
    the key the title was under.
    """
    body = (fixtures / "racingpost_owner_entries.html").read_text(encoding="utf-8")
    records = list(RacingPostSource(wathnan_config)._from_state(body))
    assert len(records) == 3
    races = {r.course: r for r in _group_records(records, "https://example.invalid", "racingpost")}
    assert set(races) == {"KENTUCKY DOWNS", "SALISBURY", "KEMPTON"}
    assert races["KENTUCKY DOWNS"].race_type == (
        "Mint Millions Invitational Stakes (Grade 3) (Turf)")
    assert races["KENTUCKY DOWNS"].runners[0].horse == "HAATEM"
    # Every row carries its title, not just the one that was noticed.
    assert all(race.race_type for race in races.values())


def test_racingpost_reads_entries_out_of_a_rendered_table(wathnan_config):
    html = """<html><body><h2>19 August 2026</h2><table>
      <thead><tr><th>Course</th><th>Race</th><th>Distance</th><th>Time</th><th>Horse</th>
      <th>Sire</th><th>Dam</th><th>Trainer</th><th>Jockey</th></tr></thead>
      <tbody><tr><td>Thirsk</td><td>Maiden</td><td>6f</td><td>17:33</td>
      <td>Final Objective</td><td>Sioux Nation</td><td>Sneaky Snooze</td>
      <td>Hamad Al-Jehani</td><td>James Doyle</td></tr></tbody></table></body></html>"""
    source = RacingPostSource(wathnan_config)
    records = list(source._from_tables(BeautifulSoup(html, "lxml")))
    assert len(records) == 1
    race = next(iter(_group_records(records, "https://example.invalid", "racingpost")))
    assert race.date == dt.date(2026, 8, 19)
    assert race.course == "THIRSK"
    assert race.runners[0].horse == "FINAL OBJECTIVE"


def test_racingpost_knows_irish_courses_run_on_irish_time():
    from wathnan.sources.racingpost import _is_irish
    assert _is_irish("CURRAGH") and not _is_irish("YARMOUTH")


# -- fetch behaviour ------------------------------------------------------------
def test_browser_retry_ignores_the_cached_challenge_page(tmp_path, wathnan_config):
    """A blocked plain fetch must not hand its own cached body to the retry."""
    from dataclasses import replace as _replace

    from wathnan.sources.base import Fetcher

    config = _replace(wathnan_config, snapshot_dir=tmp_path)
    fetcher = Fetcher(config)
    url = "https://example.invalid/owner"

    calls = {"plain": 0, "browser": 0}

    def plain(_url, _headers):
        calls["plain"] += 1
        return "<title>Pardon Our Interruption</title>"

    def browsered(_url):
        calls["browser"] += 1
        return "<table><thead><tr><th>Horse</th></tr></thead></table>"

    fetcher._get_with_requests = plain
    fetcher._get_with_browser = browsered

    body = EquibaseSource(config)._load(fetcher, url)
    assert calls == {"plain": 1, "browser": 1}
    assert "Pardon" not in body
    # The challenge page was not left behind for a later --offline run.
    assert not fetcher.snapshot_path(url).exists() or \
        "Pardon" not in fetcher.snapshot_path(url).read_text()


def test_snapshots_are_reused_within_the_hour(tmp_path, wathnan_config):
    from dataclasses import replace as _replace

    from wathnan.sources.base import Fetcher

    fetcher = Fetcher(_replace(wathnan_config, snapshot_dir=tmp_path))
    url = "https://example.invalid/page"
    calls = []

    def plain(_url, _headers):
        calls.append(_url)
        return "<html>ok</html>"

    fetcher._get_with_requests = plain
    assert fetcher.get(url) == "<html>ok</html>"
    assert fetcher.get(url) == "<html>ok</html>"
    assert len(calls) == 1, "the second call should come from the snapshot"


def test_offline_without_a_snapshot_is_an_error(tmp_path, wathnan_config):
    from dataclasses import replace as _replace

    from wathnan.sources.base import Fetcher, FetchError

    fetcher = Fetcher(_replace(wathnan_config, snapshot_dir=tmp_path, offline=True))
    with pytest.raises(FetchError):
        fetcher.get("https://example.invalid/missing")


# -- Sporting Life (the fallback for both blocked feeds) -------------------------
class _JsonFetcher:
    """Serves the captured API responses by URL pattern."""

    def __init__(self, fixtures):
        self.fixtures = fixtures
        self.calls = []

    def get_json(self, url, **_):
        import json as _json
        self.calls.append(url)
        if "racing/racecards/" in url:
            name = "sportinglife_day.json"
        elif "/race/933831" in url:            # the York nursery
            name = "sportinglife_race.json"
        elif "/race/" in url:                  # any other race: an empty card
            return {"race_summary": {}, "rides": []}
        elif "/horse/" in url:
            name = "sportinglife_horse.json"
        else:
            raise AssertionError(url)
        return _json.loads((self.fixtures / name).read_text(encoding="utf-8"))


def test_sportinglife_sweep_finds_the_wathnan_runner(wathnan_config, fixtures, monkeypatch):
    from dataclasses import replace as _replace

    from wathnan.sources.sportinglife import SportingLifeSource, sweep

    config = _replace(wathnan_config, entries_until=wathnan_config.tomorrow)  # one day
    source = SportingLifeSource(config)
    races = sweep(source, _JsonFetcher(fixtures))
    assert len(races) == 1
    race = races[0]
    assert race.course == "YORK"
    assert race.date == dt.date(2026, 8, 19)
    # The API publishes UTC; 16:20 UTC is 5.20pm in the UK in August --
    # exactly the time the circulated 14th August template shows for this race.
    assert race.off_time_uk == dt.time(17, 20)
    assert race.race_type == "Sky Bet Nursery Class 2"
    runner = race.runners[0]
    assert runner.horse == "RULER'S PRIDE"
    assert (runner.sire, runner.dam) == ("Mehmas", "Superiority")
    assert runner.trainer == "K R Burke"


def test_sportinglife_country_filters(wathnan_config, fixtures):
    from dataclasses import replace as _replace

    from wathnan.sources.sportinglife import NORTH_AMERICA, SportingLifeSource, sweep

    config = _replace(wathnan_config, entries_until=wathnan_config.tomorrow)
    source = SportingLifeSource(config)

    fetcher = _JsonFetcher(fixtures)
    sweep(source, fetcher, countries=NORTH_AMERICA)
    us_races = [url for url in fetcher.calls if "/race/" in url]
    assert len(us_races) == 1          # only the Saratoga card

    fetcher = _JsonFetcher(fixtures)
    sweep(source, fetcher, exclude=NORTH_AMERICA)
    gb_races = [url for url in fetcher.calls if "/race/" in url]
    assert len(gb_races) == 1          # only the York card
    assert us_races != gb_races


def test_sportinglife_race_type_wording():
    from wathnan.sources.sportinglife import _race_type

    assert _race_type("Sky Bet Lowther Stakes (Fillies' Group 2)", "1") == \
        "Sky Bet Lowther Stakes (Fillies' Group 2)"
    assert _race_type("William Hill Handicap", "5") == "Class 5 Handicap"
    assert _race_type("Sky Bet Nursery", "2") == "Sky Bet Nursery Class 2"
    assert _race_type("Some Sponsor Maiden Stakes", "4") == "Maiden"
    assert _race_type("Race 1 - Claiming", "") == "Claimer"


def test_blocked_feeds_fall_back_to_sportinglife(wathnan_config, fixtures, monkeypatch):
    """Racing Post and Equibase swap to the open feed when their WAF blocks us."""
    from dataclasses import replace as _replace

    from wathnan.sources.base import FetchError
    from wathnan.sources.equibase import EquibaseSource
    from wathnan.sources.racingpost import RacingPostSource

    class _Blocked(_JsonFetcher):
        def get(self, url, **_):
            raise FetchError("406 from the WAF")

    config = _replace(wathnan_config, entries_until=wathnan_config.tomorrow)  # one day

    races = RacingPostSource(config).fetch(_Blocked(fixtures))
    assert [race.course for race in races] == ["YORK"]

    races = EquibaseSource(config).fetch(_Blocked(fixtures))
    # The fixture's Saratoga card has no Wathnan runner, so the sweep is empty
    # -- but it ran, rather than raising.
    assert races == []


# -- horse suffix lookup --------------------------------------------------------
def test_suffix_day_slug_matches_irishracing_urls():
    from wathnan.sources.suffixes import _day_slug

    assert _day_slug(dt.date(2026, 8, 20)) == "Thu-20th-Aug-2026"
    assert _day_slug(dt.date(2026, 8, 1)) == "Sat-1st-Aug-2026"
    assert _day_slug(dt.date(2026, 8, 22)) == "Sat-22nd-Aug-2026"
    assert _day_slug(dt.date(2026, 8, 23)) == "Sun-23rd-Aug-2026"


def test_suffix_source_only_covers_british_and_irish_courses():
    from wathnan.sources.suffixes import covers

    assert covers("YORK") and covers("Curragh") and covers("WOLVERHAMPTON")
    assert not covers("LA TESTE-BASSIN ARCACHON")
    assert not covers("PENN NATIONAL")
    assert not covers("")


def test_suffixes_are_read_from_horse_links():
    from wathnan.sources.suffixes import _suffixes

    page = ('<a href="/horse/Old-Is-Gold-IRE/1184426">x</a>'
            '<a href="/horse/Opportunity-GB/1163422">y</a>'
            '<a href="/horse/Quai-De-Bethune-FR/1158506">z</a>'
            '<a href="/trainer/K-R-Burke/194">t</a>')
    assert _suffixes(page) == {"oldisgold": "IRE", "opportunity": "GB",
                              "quaidebethune": "FR"}


def test_lookup_only_fetches_meetings_that_stage_a_wanted_race(wathnan_config):
    from wathnan.models import Race, Runner
    from wathnan.sources.suffixes import lookup

    day = ('<a href="/racecards/Thu-20th-Aug-2026/York/1350">r1</a>'
           '<a href="/racecards/Thu-20th-Aug-2026/Lingfield/1410">r2</a>')
    race_page = '<a href="/horse/Naval-Light-GB/999">n</a>'

    class _Fetcher:
        def __init__(self):
            self.urls = []

        def get(self, url, **_):
            self.urls.append(url)
            return day if url.endswith("Thu-20th-Aug-2026") else race_page

    fetcher = _Fetcher()
    races = [Race(date=dt.date(2026, 8, 20), course="YORK", race_type="Nursery",
                  runners=(Runner("Naval Light"),))]
    found = lookup(fetcher, races, {"navallight"})

    assert found == {"navallight": "GB"}
    # The Lingfield card is never fetched: no Wathnan runner there.
    assert not any("Lingfield" in url for url in fetcher.urls)


def test_fill_suffixes_survives_a_broken_lookup(wathnan_config):
    from wathnan.enrich import fill_suffixes
    from wathnan.models import Race, Runner

    class _Broken:
        def get(self, *_, **__):
            raise RuntimeError("irishracing is down")

    races = [Race(date=dt.date(2026, 8, 20), course="YORK", race_type="Nursery",
                  runners=(Runner("NAVAL LIGHT"),))]
    assert fill_suffixes(races, _Broken()) == races


# -- entries the day sweep cannot see -------------------------------------------
def test_roster_recovers_an_entry_missing_from_the_day_card(wathnan_config, monkeypatch):
    """North American cards publish late, so a known horse is asked directly."""
    from dataclasses import replace as _replace

    from wathnan.sources import sportinglife
    from wathnan.sources.sportinglife import SportingLifeSource, sweep

    config = _replace(wathnan_config, entries_until=wathnan_config.tomorrow)
    date = config.tomorrow.isoformat()

    # The day card lists only a British meeting: no Del Mar in sight.
    day = [{"meeting_summary": {"date": date,
                                "course": {"name": "Brighton",
                                           "country": {"short_name": "ENG"}}},
            "races": [{"race_summary_reference": {"id": 111}}]}]
    horse_detail = {
        "name": "Subsanador", "sire": {"name": "Fortify"},
        "dam": {"name": "Save The Date"},
        "future_entries": [{"race_id": 222, "date": f"{date}T01:43:00",
                            "course_name": "Del Mar",
                            "race_name": "Pacific Classic Stakes"}],
    }
    del_mar = {
        "race_summary": {"name": "Race 10 - Pacific Classic Stakes - Grade 1",
                         "course_name": "Del Mar", "date": date, "time": "01:43",
                         "distance": "10f", "race_class": ""},
        "rides": [{"ride_status": "RUNNER", "owner": {"name": "Wathnan Racing"},
                   "horse": {"name": "Subsanador", "slug": "subsanador/1108225"},
                   "trainer": {"name": "R Mandella"}, "jockey": {"name": "Mike Smith"}}],
    }

    class _Fetcher:
        def get_json(self, url, **_):
            if "racecards/" in url:
                return day
            if "/race/222" in url:
                return del_mar
            if "/race/" in url:
                return {"race_summary": {}, "rides": []}
            return horse_detail

    monkeypatch.setattr(sportinglife, "load_roster", lambda: {"Subsanador": 1108225})
    races = sweep(SportingLifeSource(config), _Fetcher(),
                  countries=sportinglife.NORTH_AMERICA)

    assert [race.course for race in races] == ["DEL MAR"]
    assert races[0].runners[0].horse == "SUBSANADOR"


def test_roster_respects_the_jurisdiction_split():
    from wathnan.sources.sportinglife import NORTH_AMERICA, _in_scope

    # The Equibase fallback takes the American tracks...
    assert _in_scope("Del Mar", NORTH_AMERICA, None)
    assert not _in_scope("York", NORTH_AMERICA, None)
    # ...and the Racing Post fallback takes everything else, so one entry is
    # never reported twice.
    assert _in_scope("York", None, NORTH_AMERICA)
    assert not _in_scope("Del Mar", None, NORTH_AMERICA)


def test_roster_file_is_well_formed():
    from wathnan.sources.sportinglife import load_roster

    roster = load_roster()
    assert roster, "the roster should ship with Wathnan's known horses"
    assert all(isinstance(horse_id, int) and horse_id > 0
               for horse_id in roster.values())


def test_france_galop_strips_entry_markers_and_rider_countries():
    """A supplementary entry and a rider's licence country are not part of a name."""
    from wathnan.sources.france_galop import ENTRY_MARKER, HORSE_TAIL, _horse_name, _rider

    # "... (Sup.)" marks a supplementary entry and used to defeat the tail strip,
    # leaving the horse under two different names across two feeds.
    raw = "URGENCE F.AR. 3 a. ... (Sup.)"
    assert _horse_name(HORSE_TAIL.sub("", ENTRY_MARKER.sub("", raw))) == "URGENCE (FR)"
    assert _rider("JAMES WILLIAM DOYLE (GBR)") == "James William Doyle"
    assert _rider("MAXIME GUYON") == "Maxime Guyon"


def test_the_same_horse_from_two_feeds_merges(wathnan_config):
    """France Galop's URGENCE (FR) and the racecard feed's URGENCE are one horse."""
    from wathnan.models import Race, Runner, dedupe_races

    common = dict(date=dt.date(2026, 8, 26), course="LA TESTE-BASSIN ARCACHON",
                  race_type="Poulains Stakes", distance_furlongs=10.0,
                  off_time_uk=dt.time(17, 51))
    merged = dedupe_races([
        Race(**common, runners=(Runner("URGENCE (FR)", "Sivit Al Maury", "Urrem D'Or",
                                       "Alban de Mieulle", "James Doyle"),),
             source="france_galop"),
        Race(**common, runners=(Runner("URGENCE", "Sivit Al Maury", "Urrem D'Or",
                                       "Alban de Mieulle", "James Doyle"),),
             source="sportinglife"),
    ])
    assert len(merged) == 1
    assert len(merged[0].runners) == 1
    assert merged[0].runners[0].horse == "URGENCE (FR)"

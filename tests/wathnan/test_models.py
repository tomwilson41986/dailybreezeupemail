import datetime as dt

from wathnan.models import Breed, Race, Runner, Status, dedupe_races, group_rows


def race(day=14, course="YARMOUTH", race_type="Class 5 Handicap", time=(16, 25),
         runners=(("CREATIVE QUEEN (USA)", "Mitole", "Vigui's Heart", "William Haggas", ""),),
         distance=5.0, source="racingpost", status=Status.ENTERED):
    return Race(date=dt.date(2026, 8, day), course=course, race_type=race_type,
                distance_furlongs=distance,
                off_time_uk=dt.time(*time) if time else None,
                status=status, runners=tuple(Runner(*r) for r in runners), source=source)


def test_dedupe_merges_the_same_race_from_two_sources():
    from_rp = race(runners=(("CREATIVE QUEEN (USA)", "Mitole", "", "William Haggas", ""),))
    from_fg = race(source="france_galop", status=Status.DECLARED,
                   runners=(("CREATIVE QUEEN (USA)", "Mitole", "Vigui's Heart",
                             "William Haggas", "Cieren Fallon"),))
    merged = dedupe_races([from_rp, from_fg])
    assert len(merged) == 1
    only = merged[0]
    assert only.status is Status.DECLARED
    assert len(only.runners) == 1
    # The richer view of the runner wins.
    assert only.runners[0].dam == "Vigui's Heart"
    assert only.runners[0].jockey == "Cieren Fallon"


def test_dedupe_keeps_genuinely_different_races():
    merged = dedupe_races([race(), race(day=15, course="NEWBURY", time=(17, 23))])
    assert len(merged) == 2


def test_a_named_jockey_beats_a_blank_one():
    left = race(runners=(("SKIPPER (GB)", "Calyx", "Skippinish", "Hamad Al-Jehani", ""),))
    right = race(source="france_galop",
                 runners=(("SKIPPER (GB)", "Calyx", "Skippinish", "Hamad Al-Jehani",
                           "James Doyle"),))
    assert dedupe_races([left, right])[0].runners[0].jockey == "James Doyle"


def test_dedupe_sorts_by_date_then_course_then_time():
    races = dedupe_races([
        race(day=16, course="SOUTHWELL", time=(16, 10)),
        race(day=14, course="YARMOUTH", time=(16, 25)),
        race(day=14, course="NEWBURY", time=(17, 23)),
    ])
    assert [(r.date.day, r.course) for r in races] == [
        (14, "NEWBURY"), (14, "YARMOUTH"), (16, "SOUTHWELL")]


def test_group_rows_prints_each_date_and_course_once():
    races = [
        race(day=15, course="DEAUVILLE", race_type="Prix de Lieurey Group 3"),
        race(day=15, course="DEAUVILLE", race_type="Prix Gontaut Biron Group 3",
             runners=(("FIRST LOOK (IRE)", "Lope de Vega", "Bilissie", "André Fabre", ""),
                      ("MAP OF STARS (GB)", "Sea The Stars", "Bateel", "F-H Graffard", ""))),
        race(day=16, course="SOUTHWELL"),
    ]
    flags = [(runner.horse, show["date"], show["course"], show["race"])
             for _, runner, show in group_rows(races)]
    assert flags == [
        ("CREATIVE QUEEN (USA)", True, True, True),     # first row of 15.08 DEAUVILLE
        ("FIRST LOOK (IRE)", False, False, True),       # new race, same course
        ("MAP OF STARS (GB)", False, False, False),     # second runner in that race
        ("CREATIVE QUEEN (USA)", True, True, True),     # new day
    ]


def test_jockey_falls_back_to_tbc():
    assert Runner("SKIPPER (GB)").display_jockey() == "TBC"
    assert Runner("SKIPPER (GB)", jockey="-").display_jockey() == "TBC"
    assert Runner("SKIPPER (GB)", jockey="James Doyle").display_jockey() == "James Doyle"


def test_arabian_races_are_flagged():
    arabian = Race(date=dt.date(2026, 8, 19), course="LA TESTE", race_type="Prix De L'Afac PA",
                   breed=Breed.ARABIAN, runners=(Runner("SHARAH (FR)"),))
    assert arabian.breed is Breed.ARABIAN

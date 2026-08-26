import datetime as dt

import pytest

from wathnan.normalise import (
    clean_horse_name,
    clean_pedigree_name,
    format_clock,
    format_distance,
    format_long_date,
    ordinal,
    parse_distance,
    parse_time,
    qatar_time,
    title_course,
    title_name,
    to_uk_time,
)


@pytest.mark.parametrize("text,expected", [
    ("1600m", 8.0),
    ("2.400", 12.0),
    ("1900", 9.5),
    ("6f", 6.0),
    ("1m 2f 110y", 10.5),
    ("Six Furlongs", 6.0),
    ("One And One Sixteenth Miles", 8.5),
    ("About Seven Furlongs", 7.0),
    ("5 1/2 Furlongs", 5.5),
    ("", None),
])
def test_parse_distance(text, expected):
    assert parse_distance(text) == expected


@pytest.mark.parametrize("furlongs,expected", [(8.0, "8f"), (16.5, "16.5f"), (None, "TBC")])
def test_format_distance(furlongs, expected):
    assert format_distance(furlongs) == expected


@pytest.mark.parametrize("text,expected", [
    ("4.25pm", dt.time(16, 25)),
    ("16:35", dt.time(16, 35)),
    ("15h50", dt.time(15, 50)),
    ("12.00am", dt.time(0, 0)),
    ("-", None),
])
def test_parse_time(text, expected):
    assert parse_time(text) == expected


def test_french_post_time_converts_to_uk_and_qatar():
    """Deauville 4.25pm local is 3.25pm UK and 5.25pm in Doha, as on the report."""
    date = dt.date(2026, 8, 15)
    uk = to_uk_time(parse_time("16h25"), date, country="FR")
    assert format_clock(uk) == "3.25pm"
    assert format_clock(qatar_time(uk, date)) == "5.25pm"


def test_qatar_is_three_hours_ahead_in_winter():
    """Qatar is UTC+3 all year, so the gap widens once the UK leaves BST."""
    date = dt.date(2026, 12, 5)
    uk = parse_time("2.10pm")
    assert format_clock(qatar_time(uk, date)) == "5.10pm"


def test_us_post_time_converts_from_the_track_timezone():
    date = dt.date(2026, 8, 15)
    uk = to_uk_time(parse_time("1.30pm"), date, course="DEL MAR", country="US")
    assert format_clock(uk) == "9.30pm"


@pytest.mark.parametrize("raw,expected", [
    ("Estithmar (FR)", "ESTITHMAR (FR)"),
    ("FIRE BULLET IRE", "FIRE BULLET (IRE)"),
    ("map of stars (gb)", "MAP OF STARS (GB)"),
    ("Flash", "FLASH"),
])
def test_clean_horse_name(raw, expected):
    assert clean_horse_name(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("ALBAN DE MIEULLE", "Alban de Mieulle"),
    ("MME JF. BERNARD", "JF Bernard"),
    ("A.DE MIEULLE", "A. de Mieulle"),
    ("Hamad Al-Jehani", "Hamad Al-Jehani"),
    ("FRANCIS-HENRI GRAFFARD", "Francis-Henri Graffard"),
    ("MR JEAN-PIERRE-JOSEPH DUBOIS", "Jean-Pierre-Joseph Dubois"),
])
def test_title_name(raw, expected):
    assert title_name(raw) == expected


def test_clean_pedigree_name_drops_the_country():
    assert clean_pedigree_name("De Treville (GB)") == "De Treville"


def test_headline_dates():
    assert format_long_date(dt.date(2026, 8, 14)) == "FRIDAY 14TH AUGUST"
    assert [ordinal(n) for n in (1, 2, 3, 11, 12, 13, 21, 22)] == \
        ["1ST", "2ND", "3RD", "11TH", "12TH", "13TH", "21ST", "22ND"]


# -- courses one feed names differently from another ----------------------------
def test_course_aliases_converge_on_one_spelling():
    """A course spelt two ways must reach one name or it prints as two rows.

    Both pairs below were live: Racing Post's owner entries page says ``Epsom``
    where the Sporting Life racecard says ``Epsom Downs``, and Racing Post still
    uses ``Longchamp`` where France Galop uses the course's current name.
    """
    assert title_course("Epsom Downs") == title_course("Epsom") == "EPSOM"
    assert (title_course("Longchamp") == title_course("ParisLongchamp")
            == "PARIS LONGCHAMP")

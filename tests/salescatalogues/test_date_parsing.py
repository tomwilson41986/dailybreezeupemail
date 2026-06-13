from datetime import date

import pytest

from salescatalogues.sources.base import parse_date_range

REF = date(2026, 6, 9)


@pytest.mark.parametrize(
    "text,start,end",
    [
        # day-first, explicit year
        ("6 – 8 Oct 2026", date(2026, 10, 6), date(2026, 10, 8)),
        ("2 Sep 2026", date(2026, 9, 2), None),
        ("7 – 9 Jul 2026", date(2026, 7, 7), date(2026, 7, 9)),
        ("From 5 to 8 December 2026", date(2026, 12, 5), date(2026, 12, 8)),
        ("The 15 December 2026", date(2026, 12, 15), None),
        ("18 & 19 November 2026", date(2026, 11, 18), date(2026, 11, 19)),
        ("Friday, 5th June 2026", date(2026, 6, 5), None),
        # cross-month
        ("30 January - 4 February 2026", date(2026, 1, 30), date(2026, 2, 4)),
        ("16th October and 17th October 2026", date(2026, 10, 16), date(2026, 10, 17)),
        # year inferred (nearest upcoming)
        ("16 - 21 January", date(2027, 1, 16), date(2027, 1, 21)),
        ("11 June", date(2026, 6, 11), None),
        # a trailing clock time must not leak its hour as a day-of-month
        # (Goffs publishes the London Sale as "15 June from 5pm")
        ("15 June from 5pm", date(2026, 6, 15), None),
        ("6 - 8 October 2026 from 10:30am", date(2026, 10, 6), date(2026, 10, 8)),
    ],
)
def test_dayfirst(text, start, end):
    assert parse_date_range(text, REF, dayfirst=True) == (start, end)


@pytest.mark.parametrize(
    "text,start,end",
    [
        ("Sept. 14 - 26, 2026", date(2026, 9, 14), date(2026, 9, 26)),
        ("Nov. 3 - 10, 2026", date(2026, 11, 3), date(2026, 11, 10)),
        ("Jan. 11 - 14, 2027", date(2027, 1, 11), date(2027, 1, 14)),
        ("Oct 08 - 13", date(2026, 10, 8), date(2026, 10, 13)),
        ("June 16 – 18, 2026", date(2026, 6, 16), date(2026, 6, 18)),
        ("Nov. 11, 2026", date(2026, 11, 11), None),
    ],
)
def test_monthfirst(text, start, end):
    assert parse_date_range(text, REF, dayfirst=False) == (start, end)


def test_no_month_returns_none():
    assert parse_date_range("Coming soon", REF) == (None, None)
    assert parse_date_range("", REF) == (None, None)

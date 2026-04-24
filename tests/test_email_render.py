from datetime import date, time

from dailybreezeup.emailer import render


def _row(**over):
    base = {
        "horse": "Test Colt",
        "bred": "IRE",
        "sale_name": "Tattersalls Craven Breeze Up Sale",
        "vendor": "tattersalls",
        "lot": "12",
        "price": 200000,
        "currency": "GBP",
        "withdrawn": False,
        "course": "Newbury",
        "race_name": "Maiden Stakes",
        "race_date": date(2026, 4, 24),
        "off_time": time(14, 30),
        "trainer": "Mr Trainer",
        "jockey": "Mr Jockey",
        "draw": "5",
        "finishing_position": "1",
        "sp": "3/1",
        "year_foaled": 2024,
        "race_id": "r1",
    }
    base.update(over)
    return base


def test_render_includes_counts_and_horse():
    p = render(
        run_date=date(2026, 4, 24),
        ran_yesterday=[_row()],
        declared=[_row(finishing_position=None, sp=None)],
        entered=[],
    )
    assert "Test Colt" in p.html
    assert "£200,000" in p.html
    assert "Ran yesterday (1)" in p.html
    assert "Declared today / tomorrow (1)" in p.html
    assert "2 horses" in p.subject
    assert "Test Colt" in p.text


def test_render_empty():
    p = render(
        run_date=date(2026, 4, 24), ran_yesterday=[], declared=[], entered=[],
    )
    assert "0 horses" in p.subject
    assert "No breeze-up graduates matched" in p.html

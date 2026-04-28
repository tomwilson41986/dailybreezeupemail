from datetime import date, time

from dailybreezeup.emailer import render


def _entered_row(**over):
    base = {
        "sale_name": "Tattersalls Craven Breeze Up Sale 2026",
        "sale_co": "Tattersalls",
        "lot": "16",
        "lot_id": "rp-5-2026-04-14-16",
        "horse_uid": 8688568,
        "horse_name": "",  # unnamed
        "sire": "Havana Grey",
        "dam": "Hot Secret",
        "damsire": "Sakhee's Secret",
        "sex": "F",
        "age": 2,
        "seller": "From Yeomanstown Stud, Ireland",
        "buyer": "Stroud Coleman Bloodstock",
        "price": "GBG 350,000",
        "race_uid": "910567",
        "course": "Newmarket",
        "race_date": date(2026, 10, 3),
        "race_url": "https://www.racingpost.com/racecards/38/newmarket/2026-10-03/910567",
    }
    base.update(over)
    return base


def _ran_row(**over):
    base = _entered_row(**over)
    base.update({
        "off_time": time(14, 30),
        "race_name": "Maiden Stakes",
        "finishing_position": "1",
        "sp": "3/1",
        "race_url": "https://www.racingpost.com/results/38/newmarket/2026-04-24/912345",
    })
    return base


def test_render_shows_entered_and_ran_sections():
    p = render(
        run_date=date(2026, 4, 24),
        entered=[_entered_row()],
        ran_today=[_ran_row(horse_name="Named Runner")],
    )
    assert "Ran today (1)" in p.html
    assert "Entered in the next 5 days (1)" in p.html
    assert "Havana Grey" in p.html
    assert "Named Runner" in p.html
    # Unnamed lot should render as "Lot 16 (unnamed)"
    assert "Lot 16 (unnamed)" in p.html
    assert "2 horses" in p.subject


def test_render_window_label_reflects_setting():
    p = render(
        run_date=date(2026, 4, 24),
        entered=[_entered_row()],
        ran_today=[],
        entries_window_days=9999,
    )
    assert "Entered in the next 9999 days (1)" in p.html
    assert "ENTERED IN NEXT 9999 DAYS (1)" in p.text


def test_render_empty_case():
    p = render(run_date=date(2026, 4, 24), entered=[], ran_today=[])
    assert "0 horses" in p.subject
    assert "No breeze-up graduates ran today" in p.html
    assert "next 5 days" in p.html  # default window when not specified


def test_render_empty_case_includes_diagnostics():
    p = render(
        run_date=date(2026, 4, 24),
        entered=[],
        ran_today=[],
        diagnostics={"mode": "live", "sales_found": 0, "dedup_dropped_entered": 3},
    )
    assert "Run diagnostics" in p.html
    assert "sales_found" in p.html
    assert "dedup_dropped_entered" in p.text
    assert "mode: live" in p.text


def test_render_links_race_urls_in_html():
    row = _ran_row()
    p = render(run_date=date(2026, 4, 24), entered=[], ran_today=[row])
    assert row["race_url"] in p.html


def test_text_variant_is_plain():
    p = render(
        run_date=date(2026, 4, 24),
        entered=[_entered_row()],
        ran_today=[],
    )
    assert "ENTERED IN NEXT 5 DAYS (1)" in p.text
    assert "Havana Grey" in p.text

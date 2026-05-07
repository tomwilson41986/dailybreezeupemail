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


def test_morning_renders_entries_only():
    p = render(
        run_date=date(2026, 4, 24),
        entered=[_entered_row()],
        ran_today=[_ran_row(horse_name="Named Runner")],  # ignored in morning mode
        mode="morning",
    )
    assert "Entries &amp; declarations" in p.html
    assert "next 3 days" in p.html
    assert "Havana Grey" in p.html
    assert "Lot 16 (unnamed)" in p.html
    assert "Ran today" not in p.html
    assert "Named Runner" not in p.html
    assert p.subject.startswith("Breeze-up entries")


def test_evening_renders_results_only():
    p = render(
        run_date=date(2026, 4, 24),
        entered=[_entered_row()],  # ignored in evening mode
        ran_today=[_ran_row(horse_name="Named Runner")],
        mode="evening",
    )
    assert "Ran today" in p.html
    assert "Named Runner" in p.html
    assert "Entries" not in p.html
    assert p.subject.startswith("Breeze-up results")
    assert "1 horse" in p.subject


def test_evening_no_results_shows_placeholder():
    p = render(
        run_date=date(2026, 4, 24),
        entered=[],
        ran_today=[],
        mode="evening",
    )
    assert "No Results Today" in p.html
    assert "No Results Today" in p.subject
    assert "No Results Today" in p.text


def test_morning_window_label_reflects_setting():
    p = render(
        run_date=date(2026, 4, 24),
        entered=[_entered_row()],
        ran_today=[],
        entries_window_days=9999,
        mode="morning",
    )
    assert "next 9999 days" in p.html
    assert "NEXT 9999 DAYS" in p.text


def test_morning_empty_case():
    p = render(
        run_date=date(2026, 4, 24), entered=[], ran_today=[], mode="morning",
    )
    assert "0 horses" in p.subject
    assert "No breeze-up graduates entered" in p.html
    assert "next 3 days" in p.html  # default window when not specified


def test_render_empty_case_omits_diagnostics():
    p = render(
        run_date=date(2026, 4, 24),
        entered=[],
        ran_today=[],
        diagnostics={"run_kind": "live", "sales_found": 0, "dedup_dropped_entered": 3},
        mode="evening",
    )
    assert "Run diagnostics" not in p.html
    assert "sales_found" not in p.html
    assert "dedup_dropped_entered" not in p.text
    assert "run_kind" not in p.text


def test_render_links_race_urls_in_html():
    row = _ran_row()
    p = render(
        run_date=date(2026, 4, 24), entered=[], ran_today=[row], mode="evening",
    )
    assert row["race_url"] in p.html


def test_render_embeds_silk_cid_when_silk_url_present():
    row = _ran_row(silk_url="https://www.rp-assets.com/svg/d/1/5/361251d.svg")
    p = render(
        run_date=date(2026, 4, 24), entered=[], ran_today=[row], mode="evening",
    )
    # render() assigns row["silk_cid"] in place
    assert row.get("silk_cid")
    assert f'src="cid:{row["silk_cid"]}"' in p.html


def test_render_skips_silk_when_url_missing():
    row = _ran_row()
    p = render(
        run_date=date(2026, 4, 24), entered=[], ran_today=[row], mode="evening",
    )
    assert "silk_cid" not in row
    assert "cid:silk-" not in p.html


def test_text_variant_is_plain():
    p = render(
        run_date=date(2026, 4, 24),
        entered=[_entered_row()],
        ran_today=[],
        mode="morning",
    )
    assert "ENTRIES & DECLARATIONS" in p.text
    assert "Havana Grey" in p.text


def test_invalid_mode_rejected():
    import pytest
    with pytest.raises(ValueError):
        render(run_date=date(2026, 4, 24), entered=[], ran_today=[], mode="midday")

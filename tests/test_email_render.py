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


def test_finish_position_renders_total_runners():
    row = _ran_row()
    row["finishing_position"] = "4"
    row["total_runners"] = 10
    p = render(
        run_date=date(2026, 4, 24), entered=[], ran_today=[row], mode="evening",
    )
    assert "/ 10" in p.html
    assert "Finish 4 / 10" in p.text


def test_finish_position_omits_total_when_missing():
    row = _ran_row()
    row["finishing_position"] = "4"
    # total_runners absent
    p = render(
        run_date=date(2026, 4, 24), entered=[], ran_today=[row], mode="evening",
    )
    assert "Finish 4 " in p.text
    assert "/ 10" not in p.html


def test_morning_renders_off_time_when_present():
    row = _entered_row(off_time=time(14, 30), race_name="Maiden Stakes")
    p = render(
        run_date=date(2026, 4, 24),
        entered=[row],
        ran_today=[],
        mode="morning",
    )
    assert "14:30" in p.html
    assert "14:30" in p.text
    assert "Maiden Stakes" in p.html
    assert "Maiden Stakes" in p.text


def test_morning_omits_off_time_when_missing():
    p = render(
        run_date=date(2026, 4, 24),
        entered=[_entered_row()],
        ran_today=[],
        mode="morning",
    )
    assert "Sat 03 Oct" in p.html


def test_sl_go_label_replaces_going():
    row = _entered_row(
        sheet_matched=True,
        sheet_breeze_rating=None,
        sheet_precocity_rating=None,
        sheet_ot_rank=None,
        sheet_sl_1f=11.25,
        sheet_sl_go=0.42,
    )
    p = render(
        run_date=date(2026, 4, 24),
        entered=[row],
        ran_today=[],
        mode="morning",
    )
    assert "SL GO 0.42" in p.html
    assert "SL GO 0.42" in p.text
    assert "Going" not in p.html
    assert "Going" not in p.text


def test_invalid_mode_rejected():
    import pytest
    with pytest.raises(ValueError):
        render(run_date=date(2026, 4, 24), entered=[], ran_today=[], mode="midday")


# ── Season-to-date summary section ──────────────────────────────────────────

def _season_summary(**over):
    """A populated summary with one band, one sale, one top-rated horse —
    enough to assert every sub-section renders. Used by the tests below."""
    from dailybreezeup.stats import BandStat, SaleStat, HorseSummary
    base = {
        "total_runs": 12,
        "low_n_threshold": 10,
        "by_breeze_band": [
            BandStat("≥100", n_runners=12, n_winners=3, strike_rate=0.25,
                     avg_rpr=78.5, low_n=False),
            BandStat("70–79", n_runners=4, n_winners=0, strike_rate=0.0,
                     avg_rpr=65.0, low_n=True),
        ],
        "by_precocity_band": [
            BandStat("≥100", n_runners=6, n_winners=2, strike_rate=0.333,
                     avg_rpr=80.0, low_n=True),
        ],
        "by_sale": [
            SaleStat("Craven 2026", "Craven", 2026, n_runners=12, n_winners=3,
                     strike_rate=0.25, avg_rpr=78.5, low_n=False),
        ],
        "top_breeze": [
            HorseSummary(
                horse_name="Hot Havana", lot_label="Lot 16",
                sale_label="Craven 2026", rating=92.5, peak_rpr=88,
                n_runs=2, n_wins=1, n_placed=0,
                status_label="WON", status_kind="won",
            ),
        ],
        "top_precocity": [
            HorseSummary(
                horse_name="Hot Havana", lot_label="Lot 16",
                sale_label="Craven 2026", rating=90.0, peak_rpr=88,
                n_runs=2, n_wins=1, n_placed=0,
                status_label="WON", status_kind="won",
            ),
        ],
    }
    base.update(over)
    return base


def test_evening_renders_season_summary_in_html_and_text():
    summary = _season_summary()
    p = render(
        run_date=date(2026, 5, 20),
        entered=[],
        ran_today=[_ran_row()],
        mode="evening",
        season_summary=summary,
    )
    # Section header and overall count
    assert "Season to date" in p.html
    assert "SEASON TO DATE" in p.text
    assert "12 runs" in p.html
    assert "12 runs" in p.text
    # Per-band table content
    assert "Form by Breeze rating" in p.html
    assert "FORM BY BREEZE RATING" in p.text
    assert "≥100" in p.html
    assert "25%" in p.html
    # Per-sale table
    assert "Form by Sale" in p.html
    assert "Craven 2026" in p.html
    # Top lists with status badge + peak RPR
    assert "Top 10 by Breeze rating" in p.html
    assert "Hot Havana" in p.html
    assert "WON" in p.html
    assert "88" in p.html  # peak RPR
    # Footnote about italic = small sample
    assert "small sample" in p.html
    assert "n &lt; 10" in p.html


def test_evening_low_n_band_has_muted_inline_style():
    """Bands flagged low_n must render in muted grey italic so a 1/2 SR
    doesn't compete visually with a 38/150 SR."""
    summary = _season_summary()
    p = render(
        run_date=date(2026, 5, 20),
        entered=[],
        ran_today=[_ran_row()],
        mode="evening",
        season_summary=summary,
    )
    # The 70–89 band is low_n=True in the fixture — its row should carry
    # the muted style. We assert the style fragment appears somewhere in
    # the band-row markup.
    assert "color:#999;font-style:italic" in p.html


def test_morning_omits_season_summary_even_if_passed():
    """The summary block is evening-only. The morning email gates it off
    in render() so a stray summary passed in doesn't leak into morning."""
    summary = _season_summary()
    p = render(
        run_date=date(2026, 5, 20),
        entered=[_entered_row()],
        ran_today=[],
        mode="morning",
        season_summary=summary,
    )
    assert "Season to date" not in p.html
    assert "SEASON TO DATE" not in p.text


def test_evening_without_summary_skips_section():
    p = render(
        run_date=date(2026, 5, 20),
        entered=[],
        ran_today=[_ran_row()],
        mode="evening",
        season_summary=None,
    )
    assert "Season to date" not in p.html
    assert "SEASON TO DATE" not in p.text


def _weekly_row(**over):
    # Archive-sourced rows carry no race_url / silk_url — the weekly template
    # must render them without links rather than blowing up.
    base = _ran_row(horse_name="Weekly Runner", rpr=74)
    base.pop("race_url")
    base.update(over)
    return base


def test_weekly_renders_week_results_with_dates():
    p = render(
        run_date=date(2026, 7, 10),
        entered=[_entered_row()],  # ignored in weekly mode
        ran_today=[_weekly_row(race_date=date(2026, 7, 7))],
        mode="weekly",
    )
    assert "Ran this week" in p.html
    assert "Weekly Runner" in p.html
    assert "Tue 07 Jul" in p.html          # weekly cards show the run date
    assert "RPR 74" in p.html
    assert "workbook attached" in p.html
    assert p.subject.startswith("Breeze-up weekly summary")
    assert "RAN THIS WEEK" in p.text
    assert "Tue 07 Jul" in p.text


def test_weekly_quiet_week_shows_placeholder():
    p = render(run_date=date(2026, 7, 10), entered=[], ran_today=[], mode="weekly")
    assert "No Runners This Week" in p.html
    assert "No Runners" in p.subject


def test_entries_card_shows_trainer_and_jockey():
    p = render(
        run_date=date(2026, 4, 24),
        entered=[_entered_row(trainer="Karl Burke", jockey="Clifford Lee")],
        ran_today=[],
        mode="morning",
    )
    assert "Karl Burke" in p.html
    assert "Clifford Lee" in p.html
    assert "T Karl Burke  ·  J Clifford Lee" in p.text


def test_results_card_shows_trainer_and_jockey():
    p = render(
        run_date=date(2026, 4, 24),
        entered=[],
        ran_today=[_ran_row(horse_name="Named Runner",
                            trainer="Saeed bin Suroor", jockey="Oisin Orr")],
        mode="evening",
    )
    assert "Saeed bin Suroor" in p.html
    assert "Oisin Orr" in p.html
    assert "T Saeed bin Suroor  ·  J Oisin Orr" in p.text


def test_card_shows_trainer_alone_when_jockey_not_yet_booked():
    """Entries a few days out have a trainer but no jockey — the card must
    show the trainer without a dangling separator or an empty J label."""
    p = render(
        run_date=date(2026, 4, 24),
        entered=[_entered_row(trainer="Karl Burke")],
        ran_today=[],
        mode="morning",
    )
    assert "T</span> Karl Burke" in p.html
    assert ">J</span>" not in p.html
    assert "T Karl Burke\n" in p.text
    assert "J " not in p.text


def test_card_omits_connections_line_when_neither_known():
    p = render(
        run_date=date(2026, 4, 24),
        entered=[_entered_row()],
        ran_today=[],
        mode="morning",
    )
    assert ">T</span>" not in p.html
    assert ">J</span>" not in p.html


def test_evening_card_shows_rpr_when_present():
    p = render(
        run_date=date(2026, 4, 24),
        entered=[],
        ran_today=[_ran_row(horse_name="Named Runner", rpr=88)],
        mode="evening",
    )
    assert "RPR 88" in p.html
    assert "RPR 88" in p.text

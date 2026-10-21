import csv
import io
from datetime import date

import pytest

from gunrunner import csvout, emailer, report
from gunrunner.cache import Cache
from gunrunner.enrich import Enricher
from gunrunner.family import FamilyBuilder
from gunrunner.forecast import Forecaster
from gunrunner.score import assess
from gunrunner.website import Website

from .helpers import cand
from .test_family import FakeSession


@pytest.fixture
def rows(ww, tmp_path):
    cache = Cache(tmp_path / "c.sqlite")
    sess = FakeSession({})
    en = Enricher(
        ww,
        Forecaster(ww),
        Website("http://s", sess, cache),
        FamilyBuilder("http://b", sess, cache, ww),
        None,
    )
    return [
        assess(en.profile(cand(lot_id="a:1", sire="Tapit", dam="Route Queen"))),
        assess(
            en.profile(
                cand(
                    lot_id="a:2",
                    lot_no="2",
                    name="Queen's Gift",
                    sire="Curlin",
                    dam="Route Queen",
                    yob=2020,
                    sex="M",
                )
            )
        ),
    ]


def test_csv(rows):
    text = csvout.to_csv(rows, {"a:2"}, ranked=True)
    lines = text.strip().splitlines()
    assert lines[0].startswith("Rank,Match,Qualifies") and len(lines) == 3
    assert "Queen's Gift" in lines[2] and ",Yes," in lines[2]
    parsed = list(csv.reader(io.StringIO(text)))
    assert {len(r) for r in parsed} == {len(csvout.HEADERS)}


def test_report_pages(rows):
    html = report.build(
        rows,
        run_date=date(2026, 10, 23),
        scored=2,
        sales=[{"house": "Keeneland", "females": 2}],
        new_ids={"a:2"},
        silks={},
    )
    assert html.count('class="page horse"') == 2
    assert (
        "Forecast distance fit" in html and "Queen&#x27;s Gift" in html and "New this week" in html
    )
    assert "Gun Runner<br>Mare Prospects" in html


def test_email_attachments(rows, tmp_path):
    pdf = tmp_path / "Gun Runner Mare Prospects 2026-10-23.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    csvf = tmp_path / "prospects.csv"
    csvf.write_text("a,b\n")
    mail = emailer.compose(
        rows, run_date=date(2026, 10, 23), scored=2, new_ids={"a:2"}, attachments=[pdf, csvf]
    )
    assert mail.subject == "Gun Runner Mare Prospects — Fri 23 Oct 2026 (2, 1 new)"
    msg = emailer.build_message(mail, "desk@example.com", ["a@example.com", "b@example.com"])
    names = [p.get_filename() for p in msg.iter_attachments()]
    assert names == [pdf.name, "prospects.csv"]
    assert msg["To"] == "a@example.com, b@example.com"

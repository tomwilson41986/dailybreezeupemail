"""End to end checks with the network stubbed out."""

import datetime as dt
from dataclasses import replace

import pdfplumber
import pytest

from wathnan import pipeline
from wathnan.cli import build_parser, main, make_config
from wathnan.config import build_config
from wathnan.models import Race, Runner, Status
from wathnan.sources import SOURCES
from wathnan.sources.base import Source, SourceResult


class _Stub(Source):
    name = "racingpost"
    label = "Stub"
    home = "https://example.invalid"
    races: list[Race] = []
    boom: str | None = None

    def fetch(self, fetcher):
        if self.boom:
            raise RuntimeError(self.boom)
        return list(self.races)


@pytest.fixture
def stubbed(monkeypatch):
    def install(races, boom=None):
        stub = type("Installed", (_Stub,), {"races": races, "boom": boom})
        monkeypatch.setitem(SOURCES, "racingpost", stub)
        return stub
    return install


def _race(day, course="YARMOUTH", horse="CREATIVE QUEEN (USA)"):
    return Race(date=dt.date(2026, 8, day), course=course, race_type="Class 5 Handicap",
                distance_furlongs=5.0, off_time_uk=dt.time(16, 25), status=Status.DECLARED,
                runners=(Runner(horse, "Mitole", "Vigui's Heart", "William Haggas",
                                "Cieren Fallon"),), source="racingpost")


def test_run_splits_tomorrow_from_the_entry_window(tmp_path, stubbed):
    stubbed([_race(14), _race(16, "SOUTHWELL", "SKIPPER (GB)"), _race(30, "YORK")])
    config = replace(build_config(today=dt.date(2026, 8, 13)),
                     sources=("racingpost",), output_dir=tmp_path,
                     snapshot_dir=tmp_path / "snap")
    summary = pipeline.run(config)

    assert [race.date.day for race in summary.tomorrow] == [14]
    assert [race.date.day for race in summary.entries] == [16]      # the 30th is out of range
    assert summary.output.exists()
    assert summary.runner_count == 2


def test_a_failing_source_does_not_sink_the_run(tmp_path, stubbed):
    stubbed([], boom="403 from the WAF")
    config = replace(build_config(today=dt.date(2026, 8, 13)),
                     sources=("racingpost",), output_dir=tmp_path,
                     snapshot_dir=tmp_path / "snap")
    summary = pipeline.run(config)

    assert summary.failed and "403" in summary.failed[0].error
    assert summary.output.exists()
    # The failure is recorded on the PDF so nobody mistakes it for "no runners".
    with pdfplumber.open(summary.output) as pdf:
        assert "not available for this run" in (pdf.pages[0].extract_text() or "")


def test_summary_reads_as_a_report(tmp_path, stubbed):
    stubbed([_race(14)])
    config = replace(build_config(today=dt.date(2026, 8, 13)),
                     sources=("racingpost",), output_dir=tmp_path,
                     snapshot_dir=tmp_path / "snap")
    described = pipeline.run(config).describe()
    assert "Tomorrow's runners: 1" in described
    assert "Wrote" in described


def test_source_result_reports_counts():
    result = SourceResult(source="racingpost", races=[_race(14)])
    assert result.ok and result.runner_count == 1
    assert not SourceResult(source="x", error="boom").ok


# -- CLI ------------------------------------------------------------------------
def test_cli_defaults_to_tomorrow_plus_five_days():
    config = make_config(build_parser().parse_args(["--date", "2026-08-13"]))
    assert config.tomorrow == dt.date(2026, 8, 14)
    assert config.entries_from == dt.date(2026, 8, 15)
    assert config.entries_until == dt.date(2026, 8, 19)
    # Home authorities run before the broad GB/IRE sweep, so their post
    # times win when two feeds report the same race.
    assert config.sources == ("qrec", "deutscher_galopp", "france_galop",
                              "equibase", "racingpost")


def test_cli_rejects_an_unknown_source():
    with pytest.raises(SystemExit):
        make_config(build_parser().parse_args(["--sources", "timeform"]))


def test_cli_flags_map_onto_the_config():
    args = build_parser().parse_args(
        ["--offline", "--no-browser", "--no-snapshots", "--sources", "qrec",
         "--browser-arg=--no-sandbox", "--browser-proxy", "http://127.0.0.1:8080"])
    config = make_config(args)
    assert config.offline and not config.use_browser and not config.save_snapshots
    assert config.sources == ("qrec",)
    assert config.browser_args == ("--no-sandbox",)
    assert config.browser_proxy == "http://127.0.0.1:8080"


def test_cli_writes_to_the_requested_path(tmp_path, stubbed, capsys):
    stubbed([_race(14)])
    target = tmp_path / "nested" / "runners.pdf"
    code = main(["--date", "2026-08-13", "--sources", "racingpost",
                 "--output", str(target), "--output-dir", str(tmp_path),
                 "--snapshot-dir", str(tmp_path / "snap")])
    assert code == 0
    assert target.exists()
    assert "Wrote" in capsys.readouterr().out


def test_cli_reports_failure_when_no_source_succeeds(tmp_path, stubbed):
    stubbed([], boom="blocked")
    code = main(["--date", "2026-08-13", "--sources", "racingpost",
                 "--output-dir", str(tmp_path), "--snapshot-dir", str(tmp_path / "snap")])
    assert code == 1

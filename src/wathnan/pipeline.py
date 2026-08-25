"""Collect every source, reconcile the results and produce the report."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .enrich import canonicalise, fill_suffixes
from .models import Race, dedupe_races
from .render import build_sections, render_report
from .sources import SOURCES, Fetcher, SourceResult

LOG = logging.getLogger(__name__)


@dataclass
class RunSummary:
    """The outcome of one run, for the console and the CI job summary."""

    config: Config
    results: list[SourceResult] = field(default_factory=list)
    tomorrow: list[Race] = field(default_factory=list)
    entries: list[Race] = field(default_factory=list)
    output: Path | None = None

    @property
    def failed(self) -> list[SourceResult]:
        return [result for result in self.results if not result.ok]

    @property
    def runner_count(self) -> int:
        return sum(len(race.runners) for race in (*self.tomorrow, *self.entries))

    def notes(self) -> list[str]:
        """Footnotes printed on the PDF when a source could not be read."""
        return [f"{SOURCES[result.source].label}: not available for this run "
                f"({result.error})" for result in self.failed if result.source in SOURCES]

    def describe(self) -> str:
        lines = [
            f"Report window: {self.config.tomorrow:%d %b %Y} (runners), "
            f"{self.config.entries_from:%d %b} - {self.config.entries_until:%d %b %Y} (entries)",
            "",
            f"{'Source':<28} {'Status':<9} {'Races':>6} {'Runners':>8}",
            f"{'-' * 28} {'-' * 9} {'-' * 6} {'-' * 8}",
        ]
        for result in self.results:
            label = SOURCES[result.source].label if result.source in SOURCES else result.source
            status = "ok" if result.ok else "FAILED"
            lines.append(f"{label:<28} {status:<9} {len(result.races):>6} "
                         f"{result.runner_count:>8}")
        lines += [
            "",
            f"Tomorrow's runners: {sum(len(r.runners) for r in self.tomorrow)} "
            f"in {len(self.tomorrow)} race(s)",
            f"Updated entries:    {sum(len(r.runners) for r in self.entries)} "
            f"in {len(self.entries)} race(s)",
        ]
        for result in self.failed:
            lines.append(f"  ! {result.source}: {result.error}")
        if self.output:
            lines.append(f"\nWrote {self.output}")
        return "\n".join(lines)


def run(config: Config) -> RunSummary:
    """Fetch every configured source and write the PDF."""
    summary = RunSummary(config=config)
    fetcher = Fetcher(config)

    collected: list[Race] = []
    for name in config.sources:
        source_class = SOURCES.get(name)
        if source_class is None:
            LOG.warning("unknown source %r, skipping", name)
            continue
        LOG.info("collecting %s", name)
        result = source_class(config).collect(fetcher)
        summary.results.append(result)
        collected.extend(result.races)

    # Reconcile names once, after de-duplication, so each horse and each
    # person is decided a single time across every feed.
    races = canonicalise(dedupe_races(collected))
    if config.fill_suffixes:
        races = fill_suffixes(races, fetcher, learn=config.learn_suffixes)
    if config.learn_suffixes:
        from .sources.sportinglife import remember_roster
        remember_roster()
    summary.tomorrow = [race for race in races if race.date == config.tomorrow]
    summary.entries = [race for race in races
                       if config.entries_from <= race.date <= config.entries_until]

    sections = build_sections(summary.tomorrow, summary.entries, config.tomorrow,
                              config.entries_from, config.entries_until)
    summary.output = render_report(sections, config.output_path(), notes=summary.notes())
    return summary

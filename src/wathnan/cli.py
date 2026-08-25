"""Command line entry point: ``python -m wathnan``."""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from dataclasses import replace
from pathlib import Path

from .config import DEFAULT_SOURCES, Config, build_config, load_env_overrides
from .sources import SOURCES


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wathnan",
        description="Build the Wathnan Racing runners and entries report.",
    )
    parser.add_argument("--date", type=_date, metavar="YYYY-MM-DD",
                        help="treat this as today (the report covers the next day on)")
    parser.add_argument("--days-ahead", type=int, default=5, metavar="N",
                        help="days of entries after tomorrow (default: 5)")
    parser.add_argument("--sources", default=",".join(DEFAULT_SOURCES),
                        help=f"comma separated subset of: {', '.join(SOURCES)}")
    parser.add_argument("--output", type=Path, metavar="PATH",
                        help="write the PDF here instead of output/")
    parser.add_argument("--output-dir", type=Path, default=Path("output"),
                        help="directory for the generated PDF (default: output/)")
    parser.add_argument("--snapshot-dir", type=Path, default=Path("snapshots"),
                        help="where fetched pages are cached (default: snapshots/)")
    parser.add_argument("--offline", action="store_true",
                        help="use only saved snapshots; never touch the network")
    parser.add_argument("--no-snapshots", action="store_true",
                        help="do not write fetched pages to disk")
    parser.add_argument("--no-suffix-lookup", action="store_true",
                        help="do not look up a country suffix for unknown horses")
    parser.add_argument("--learn-suffixes", action="store_true",
                        help="record any looked-up suffix in wathnan/data/horses.json")
    parser.add_argument("--no-browser", action="store_true",
                        help="never fall back to headless Chromium for blocked sites")
    parser.add_argument("--browser-proxy", metavar="URL",
                        help="proxy for the headless browser, e.g. http://127.0.0.1:8080")
    parser.add_argument("--browser-arg", action="append", default=[], metavar="FLAG",
                        help="extra Chromium flag, e.g. --browser-arg=--no-sandbox "
                             "(repeatable; use the = form so argparse does not "
                             "mistake the flag for an option)")
    parser.add_argument("--email", action="store_true",
                        help="email the report (see SMTP_* and MAIL_TO in the README)")
    parser.add_argument("--only-at", metavar="HH",
                        help="exit without doing anything unless the local hour in "
                             "--timezone is HH; lets one UTC cron hold a fixed local time")
    parser.add_argument("--timezone", default="Europe/London", metavar="TZ",
                        help="timezone for --only-at (default: Europe/London)")
    parser.add_argument("--timeout", type=int, default=45, metavar="SECONDS")
    parser.add_argument("-v", "--verbose", action="count", default=0)
    return parser


def _date(value: str) -> dt.date:
    return dt.datetime.strptime(value, "%Y-%m-%d").date()


def make_config(args: argparse.Namespace) -> Config:
    unknown = [name for name in _split(args.sources) if name not in SOURCES]
    if unknown:
        raise SystemExit(f"unknown source(s): {', '.join(unknown)}")

    config = build_config(today=args.date, days_ahead=args.days_ahead)
    config = replace(
        config,
        sources=tuple(_split(args.sources)),
        output_dir=args.output_dir,
        snapshot_dir=args.snapshot_dir,
        offline=args.offline,
        save_snapshots=not args.no_snapshots,
        use_browser=not args.no_browser,
        fill_suffixes=not args.no_suffix_lookup,
        learn_suffixes=args.learn_suffixes,
        browser_proxy=args.browser_proxy,
        browser_args=tuple(args.browser_arg),
        request_timeout=args.timeout,
        **load_env_overrides(),
    )
    return config


def _split(value: str) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=[logging.WARNING, logging.INFO, logging.DEBUG][min(args.verbose, 2)],
        format="%(levelname)-7s %(name)s: %(message)s",
    )

    if _should_skip(args):
        return 0

    from .pipeline import run  # imported late so --help stays fast

    config = make_config(args)
    summary = run(config)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(summary.output.read_bytes())
        summary.output = args.output

    print(summary.describe())

    if args.email:
        from .mail import MailError, send
        try:
            sent_to = send(summary, summary.output)
            print(f"Emailed to {', '.join(sent_to)}")
        except MailError as exc:
            print(f"Email failed: {exc}", file=sys.stderr)
            return 2

    # A run that reached no source at all is a failure; a partial run is not.
    return 1 if summary.results and not any(result.ok for result in summary.results) else 0


def _should_skip(args: argparse.Namespace) -> bool:
    """Honour ``--only-at``: a UTC cron firing twice keeps one local hour.

    GitHub's scheduler is UTC only, so 07:00 in London needs a job at 06:00 UTC
    in summer and 07:00 UTC in winter. Scheduling both and skipping the wrong
    one keeps the delivery time fixed across the clock change.
    """
    if not args.only_at:
        return False
    from zoneinfo import ZoneInfo
    now = dt.datetime.now(ZoneInfo(args.timezone))
    if now.hour == int(args.only_at):
        return False
    print(f"Skipping: it is {now:%H:%M} in {args.timezone}, "
          f"not {int(args.only_at):02d}:00.")
    return True


if __name__ == "__main__":
    sys.exit(main())

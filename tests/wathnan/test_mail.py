"""The morning email: composition, recipients and the fixed-hour guard."""

import datetime as dt

import pytest
from template_2026_08_14 import ENTRIES, TOMORROW

from wathnan.cli import _should_skip, build_parser
from wathnan.config import build_config
from wathnan.enrich import canonicalise
from wathnan.mail import DEFAULT_RECIPIENTS, MailError, build_message, recipients, send
from wathnan.pipeline import RunSummary


@pytest.fixture
def summary(tmp_path):
    pdf = tmp_path / "wathnan-runners-2026-08-14.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake\n%%EOF\n")
    return RunSummary(config=build_config(today=dt.date(2026, 8, 13)),
                      tomorrow=canonicalise(TOMORROW), entries=canonicalise(ENTRIES),
                      output=pdf)


def _clear_mail_env(monkeypatch):
    for name in ("WATHNAN_EMAIL_TO", "MAIL_TO", "EMAIL_TO", "GMAIL_USER",
                 "GMAIL_APP_PASSWORD", "SMTP_USER", "SMTP_PASSWORD",
                 "SMTP_HOST", "SMTP_PORT", "EMAIL_FROM", "MAIL_FROM"):
        monkeypatch.delenv(name, raising=False)


def test_default_recipients_are_the_team(monkeypatch):
    _clear_mail_env(monkeypatch)
    assert recipients() == list(DEFAULT_RECIPIENTS)
    assert "racingsquared@gmail.com" in recipients()
    assert "sophie@wathnan-racing.com" in recipients()


def test_mail_to_overrides_and_tolerates_whitespace(monkeypatch):
    _clear_mail_env(monkeypatch)
    monkeypatch.setenv("MAIL_TO", " a@example.com , b@example.com ,")
    assert recipients() == ["a@example.com", "b@example.com"]


def test_this_report_has_its_own_recipient_list(monkeypatch):
    """The shared EMAIL_TO drives the breeze-up jobs; Wathnan overrides it."""
    _clear_mail_env(monkeypatch)
    monkeypatch.setenv("EMAIL_TO", "breezeup@example.com")
    assert recipients() == ["breezeup@example.com"]
    monkeypatch.setenv("WATHNAN_EMAIL_TO", "sophie@example.com;tom@example.com")
    assert recipients() == ["sophie@example.com", "tom@example.com"]


def test_a_blank_ci_variable_does_not_clobber_the_fallback(monkeypatch):
    """Actions expands an unset `${{ vars.X }}` to an empty string."""
    _clear_mail_env(monkeypatch)
    monkeypatch.setenv("WATHNAN_EMAIL_TO", "")
    monkeypatch.setenv("EMAIL_TO", "  ")
    assert recipients() == list(DEFAULT_RECIPIENTS)


def test_message_carries_the_report_and_a_digest(summary):
    message = build_message(summary, summary.output, "reports@example.com",
                            ["a@example.com", "b@example.com"])
    assert message["Subject"] == "Wathnan Racing runners – Friday 14th August"
    assert message["To"] == "a@example.com, b@example.com"

    plain = message.get_body(preferencelist=("plain",)).get_content()
    html = message.get_body(preferencelist=("html",)).get_content()
    for body in (plain, html):
        assert "4 runners declared for Friday 14th August" in body
        assert "CREATIVE QUEEN (USA)" in body
        assert "William Haggas" in body

    attachments = list(message.iter_attachments())
    assert len(attachments) == 1
    assert attachments[0].get_filename() == summary.output.name
    assert attachments[0].get_content_type() == "application/pdf"


def test_a_blank_day_still_sends(tmp_path):
    pdf = tmp_path / "empty.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    blank = RunSummary(config=build_config(today=dt.date(2026, 8, 13)), output=pdf)
    message = build_message(blank, pdf, "reports@example.com", ["a@example.com"])
    plain = message.get_body(preferencelist=("plain",)).get_content()
    assert "No runners declared for tomorrow." in plain


def test_a_failed_source_is_flagged_in_the_email(summary):
    from wathnan.sources.base import SourceResult

    summary.results = [SourceResult(source="qrec", error="timeout")]
    message = build_message(summary, summary.output, "r@example.com", ["a@example.com"])
    assert "not available for this run" in \
        message.get_body(preferencelist=("plain",)).get_content()


def test_sending_without_credentials_is_a_clear_error(summary, monkeypatch):
    _clear_mail_env(monkeypatch)
    with pytest.raises(MailError, match="GMAIL_USER"):
        send(summary, summary.output)


def test_gmail_credentials_are_enough(summary, monkeypatch):
    """The repo's shared secrets work without any wathnan-specific setup."""
    _clear_mail_env(monkeypatch)
    monkeypatch.setenv("GMAIL_USER", "reports@example.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "sixteencharacter")
    seen = {}

    class _Server:
        def __init__(self, host, port, **kwargs):
            seen["endpoint"] = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def starttls(self, **_):
            seen["starttls"] = True

        def login(self, user, _password):
            seen["login"] = user

        def send_message(self, _message):
            seen["sent"] = True

    monkeypatch.setattr("smtplib.SMTP", _Server)
    send(summary, summary.output)
    # Gmail on 587 with STARTTLS, matching the rest of the repo.
    assert seen["endpoint"] == ("smtp.gmail.com", 587)
    assert seen["starttls"] and seen["sent"]
    assert seen["login"] == "reports@example.com"


def test_send_uses_implicit_tls_on_465(summary, monkeypatch):
    _clear_mail_env(monkeypatch)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "reports@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("MAIL_TO", "a@example.com")
    sent = {}

    class _Server:
        def __init__(self, host, port, **kwargs):
            sent["endpoint"] = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def login(self, user, password):
            sent["login"] = user

        def send_message(self, message):
            sent["to"] = message["To"]

    monkeypatch.setattr("smtplib.SMTP_SSL", _Server)
    assert send(summary, summary.output) == ["a@example.com"]
    assert sent["endpoint"] == ("smtp.example.com", 465)
    assert sent["login"] == "reports@example.com"
    assert sent["to"] == "a@example.com"


def test_send_uses_starttls_on_587(summary, monkeypatch):
    _clear_mail_env(monkeypatch)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "reports@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("SMTP_PORT", "587")
    steps = []

    class _Server:
        def __init__(self, *args, **kwargs):
            steps.append("connect")

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def starttls(self, **_):
            steps.append("starttls")

        def login(self, *_):
            steps.append("login")

        def send_message(self, _):
            steps.append("send")

    monkeypatch.setattr("smtplib.SMTP", _Server)
    send(summary, summary.output)
    assert steps == ["connect", "starttls", "login", "send"]


def test_smtp_failures_surface_as_mail_errors(summary, monkeypatch):
    import smtplib

    _clear_mail_env(monkeypatch)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("SMTP_USER", "reports@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")

    def _boom(*_, **__):
        raise smtplib.SMTPAuthenticationError(535, b"nope")

    monkeypatch.setattr("smtplib.SMTP_SSL", _boom)
    with pytest.raises(MailError, match="could not send"):
        send(summary, summary.output)


# -- the fixed-hour guard -------------------------------------------------------
@pytest.mark.parametrize("utc_hour,expected_skip", [
    # In August, London is UTC+1: the 06:00 UTC job runs, the 07:00 one skips.
    (6, False),
    (7, True),
])
def test_only_at_holds_seven_am_in_summer(monkeypatch, utc_hour, expected_skip):
    _freeze(monkeypatch, dt.datetime(2026, 8, 20, utc_hour, 0))
    args = build_parser().parse_args(["--only-at", "07"])
    assert _should_skip(args) is expected_skip


@pytest.mark.parametrize("utc_hour,expected_skip", [
    # In December, London is UTC: the 07:00 UTC job runs instead.
    (6, True),
    (7, False),
])
def test_only_at_holds_seven_am_in_winter(monkeypatch, utc_hour, expected_skip):
    _freeze(monkeypatch, dt.datetime(2026, 12, 10, utc_hour, 0))
    args = build_parser().parse_args(["--only-at", "07"])
    assert _should_skip(args) is expected_skip


def test_without_only_at_the_run_always_proceeds():
    assert _should_skip(build_parser().parse_args([])) is False


def _freeze(monkeypatch, naive_utc: dt.datetime) -> None:
    """Pin ``datetime.now(tz)`` to a fixed UTC instant."""
    import wathnan.cli as cli

    real = dt.datetime

    class _Frozen(real):
        @classmethod
        def now(cls, tz=None):
            moment = naive_utc.replace(tzinfo=dt.UTC)
            return moment.astimezone(tz) if tz else moment

    monkeypatch.setattr(cli.dt, "datetime", _Frozen)

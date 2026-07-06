from datetime import date

from salescatalogues.config import _ALWAYS_RECIPIENTS, Settings

_FRIDAY = date(2026, 7, 10)
_THURSDAY = date(2026, 7, 9)


def test_always_recipients_included_even_when_unset():
    s = Settings(catalogues_email_to="", email_to="")
    assert s.email_to_list == list(_ALWAYS_RECIPIENTS)


def test_fred_is_a_baked_recipient():
    s = Settings(catalogues_email_to="", email_to="")
    assert "fred@blandfordbloodstock.com" in s.email_to_list


def test_configured_appended_and_deduped():
    # A configured address that's already an always-recipient isn't duplicated;
    # a new one is appended after the always-on block.
    s = Settings(
        catalogues_email_to="RacingSquared@gmail.com, extra@example.com",
        email_to="",
    )
    out = s.email_to_list
    assert out[: len(_ALWAYS_RECIPIENTS)] == list(_ALWAYS_RECIPIENTS)
    assert out[-1] == "extra@example.com"
    # case-insensitive dedup of the already-present always recipient
    assert sum(1 for a in out if a.lower() == "racingsquared@gmail.com") == 1


def test_falls_back_to_email_to():
    s = Settings(catalogues_email_to="", email_to="fallback@example.com")
    assert "fallback@example.com" in s.email_to_list


def test_tom_biggs_not_on_the_daily_digest():
    # He opted out of the dailies and only gets the Friday edition.
    s = Settings(catalogues_email_to="", email_to="")
    assert "tom.biggs@blandfordbloodstock.com" not in [a.lower() for a in s.email_to_list]
    assert s.recipients_for(_THURSDAY) == s.email_to_list


def test_friday_edition_includes_friday_only_recipients():
    s = Settings(catalogues_email_to="", email_to="")
    out = s.recipients_for(_FRIDAY)
    assert out[: len(_ALWAYS_RECIPIENTS)] == list(_ALWAYS_RECIPIENTS)
    assert "tom.biggs@blandfordbloodstock.com" in out


def test_friday_only_recipient_not_duplicated_when_configured():
    # An operator who explicitly configures the address keeps it daily; the
    # Friday merge must not produce a duplicate.
    s = Settings(catalogues_email_to="Tom.Biggs@blandfordbloodstock.com", email_to="")
    out = s.recipients_for(_FRIDAY)
    assert sum(1 for a in out if a.lower() == "tom.biggs@blandfordbloodstock.com") == 1

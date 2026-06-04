from __future__ import annotations

import pytest

from barriertrials.names import horse_key, strip_country
from dailybreezeup.racing.rp_racecards import normalize_name


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("GOLDEN NARRATIVE (IRE)", "GOLDEN NARRATIVE"),
        ("King's Fury (GB)", "King's Fury"),
        ("On Just Terms (USA)", "On Just Terms"),
        ("No Suffix", "No Suffix"),
        ("Trailing space (FR) ", "Trailing space"),
    ],
)
def test_strip_country(raw, expected):
    assert strip_country(raw) == expected


def test_horse_key_matches_rp_suffixless_name():
    # The sheet name (with country) must reduce to the same key RP's
    # suffix-less runner name does — that's what makes the join work.
    assert horse_key("GOLDEN NARRATIVE (IRE)") == normalize_name("Golden Narrative")
    assert horse_key("King's Fury (GB)") == normalize_name("Kings Fury")


def test_horse_key_handles_punctuation_and_case():
    assert horse_key("HIP HOP CHRISSY (IRE)") == "hiphopchrissy"

"""Unit, time and name normalisation shared by the source adapters.

Every source speaks a slightly different dialect -- metres or furlongs, local
post time or UK time, "MR ABDULLAH SAEED" or "Mr Abdullah Saeed".  Everything is
funnelled through here so the report is internally consistent.
"""

from __future__ import annotations

import datetime as dt
import re
from zoneinfo import ZoneInfo

UK = ZoneInfo("Europe/London")
QATAR = ZoneInfo("Asia/Qatar")

METRES_PER_FURLONG = 201.168

#: One component of an imperial distance: "1m", "3f", "110y".
DISTANCE_PART = re.compile(
    r"(\d+(?:\s+\d+/\d+|\.\d+|/\d+)?)\s*"
    r"(miles?|m|furlongs?|fur|f|yards?|yds?|y)\b"
)

#: Local timezone of each racing jurisdiction we pull from.
COUNTRY_TIMEZONES = {
    "GB": UK,
    "IE": ZoneInfo("Europe/Dublin"),
    "FR": ZoneInfo("Europe/Paris"),
    "DE": ZoneInfo("Europe/Berlin"),
    "ES": ZoneInfo("Europe/Madrid"),
    "QA": QATAR,
    "US": ZoneInfo("America/New_York"),
}

#: Courses whose local timezone differs from their feed's default.
COURSE_TIMEZONES = {
    "SAN SEBASTIAN": ZoneInfo("Europe/Madrid"),
    "SANTA ANITA": ZoneInfo("America/Los_Angeles"),
    "DEL MAR": ZoneInfo("America/Los_Angeles"),
    "GOLDEN GATE FIELDS": ZoneInfo("America/Los_Angeles"),
    "LOS ALAMITOS": ZoneInfo("America/Los_Angeles"),
    "ARLINGTON": ZoneInfo("America/Chicago"),
    "CHURCHILL DOWNS": ZoneInfo("America/New_York"),
    "KEENELAND": ZoneInfo("America/New_York"),
    "OAKLAWN PARK": ZoneInfo("America/Chicago"),
    "LONE STAR PARK": ZoneInfo("America/Chicago"),
    "WOODBINE": ZoneInfo("America/Toronto"),
}


def furlongs_from_metres(metres: float | int | None) -> float | None:
    """Convert metres to furlongs, rounded to the half furlong the report uses."""
    if not metres:
        return None
    return round(float(metres) / METRES_PER_FURLONG * 2) / 2


#: Equibase spells distances out: "Six Furlongs", "One And One Sixteenth Miles".
WORD_NUMBERS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
    "seven": "7", "eight": "8", "nine": "9", "ten": "10", "eleven": "11",
    "twelve": "12", "thirteen": "13", "fourteen": "14", "fifteen": "15",
    "sixteen": "16", "seventeen": "17", "eighteen": "18", "nineteen": "19",
    "twenty": "20",
}
WORD_FRACTIONS = {
    "half": "1/2", "third": "1/3", "quarter": "1/4", "fourth": "1/4",
    "eighth": "1/8", "sixteenth": "1/16", "sixty fourth": "1/64",
    "halves": "1/2", "quarters": "1/4", "eighths": "1/8", "sixteenths": "1/16",
}


def parse_distance(text: str | None) -> float | None:
    """Parse any distance string a source might hand us into furlongs.

    Handles ``1600m``, ``2.400``, ``1m 2f 110y``, ``6f``, ``5 1/2 Furlongs`` and
    Equibase's spelled-out ``One And One Sixteenth Miles``.
    """
    if not text:
        return None
    text = _numeralise(str(text).strip().lower().replace(",", ""))

    # Continental feeds write 2.400 for 2400 metres.
    metric = re.fullmatch(r"(\d)\.(\d{3})\s*m?", text)
    if metric:
        return furlongs_from_metres(int(metric.group(1) + metric.group(2)))
    metric = re.fullmatch(r"(\d{3,5})\s*(m|metres|meters)?", text)
    if metric and (metric.group(2) or int(metric.group(1)) >= 400):
        return furlongs_from_metres(int(metric.group(1)))

    total_yards = 0.0
    matched = False
    for value, unit in DISTANCE_PART.findall(text):
        matched = True
        amount = _to_float(value)
        if unit.startswith(("mile", "m")):
            total_yards += amount * 1760
        elif unit.startswith(("furlong", "fur", "f")):
            total_yards += amount * 220
        else:
            total_yards += amount
    if not matched:
        return None
    return round(total_yards / 220 * 2) / 2


def _numeralise(text: str) -> str:
    """Turn ``one and one sixteenth miles`` into ``1 1/16 miles``."""
    if not any(word in text for word in WORD_NUMBERS):
        return text
    for phrase, fraction in WORD_FRACTIONS.items():
        text = re.sub(rf"\b(?:a|one)\s+{phrase}\b", fraction, text)
        text = re.sub(rf"\b{phrase}\b", fraction, text)
    for word, digit in WORD_NUMBERS.items():
        text = re.sub(rf"\b{word}\b", digit, text)
    text = re.sub(r"\s+and\s+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _to_float(value: str) -> float:
    value = value.strip()
    whole_and_fraction = re.fullmatch(r"(\d+)\s+(\d+)/(\d+)", value)
    if whole_and_fraction:
        a, b, c = (int(g) for g in whole_and_fraction.groups())
        return a + b / c
    fraction = re.fullmatch(r"(\d+)/(\d+)", value)
    if fraction:
        return int(fraction.group(1)) / int(fraction.group(2))
    return float(value)


def format_distance(furlongs: float | None) -> str:
    """``8.0 -> '8f'``, ``16.5 -> '16.5f'``, ``None -> 'TBC'``."""
    if furlongs is None:
        return "TBC"
    if float(furlongs).is_integer():
        return f"{int(furlongs)}f"
    return f"{furlongs:g}f"


def parse_time(text: str | None) -> dt.time | None:
    """Parse ``16:35``, ``4.25pm``, ``4:25 PM``, ``16h35`` into a time."""
    if not text:
        return None
    text = str(text).strip().lower().replace(" ", "")
    match = re.fullmatch(r"(\d{1,2})[:.h](\d{2})(am|pm)?", text)
    if not match:
        match = re.fullmatch(r"(\d{1,2})(am|pm)", text)
        if not match:
            return None
        hour, minute, meridiem = int(match.group(1)), 0, match.group(2)
    else:
        hour, minute, meridiem = int(match.group(1)), int(match.group(2)), match.group(3)
    if meridiem == "pm" and hour != 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return dt.time(hour, minute)


def to_uk_time(local_time: dt.time | None, on_date: dt.date,
               tz: ZoneInfo | None = None, course: str = "",
               country: str = "GB") -> dt.time | None:
    """Convert a track's local post time into UK time on the given date."""
    if local_time is None:
        return None
    zone = tz or COURSE_TIMEZONES.get((course or "").upper()) or COUNTRY_TIMEZONES.get(country, UK)
    local = dt.datetime.combine(on_date, local_time, tzinfo=zone)
    return local.astimezone(UK).time()


def qatar_time(uk_time: dt.time | None, on_date: dt.date) -> dt.time | None:
    """Qatar is UTC+3 year round, so this is UK +2h in summer and +3h in winter."""
    if uk_time is None:
        return None
    return dt.datetime.combine(on_date, uk_time, tzinfo=UK).astimezone(QATAR).time()


def format_clock(value: dt.time | None) -> str:
    """Render a time the way the report does: ``4.25pm``, ``10.30pm``, ``TBC``."""
    if value is None:
        return "TBC"
    hour = value.hour % 12 or 12
    return f"{hour}.{value.minute:02d}{'am' if value.hour < 12 else 'pm'}"


def format_day(date: dt.date) -> str:
    """``14.08`` -- the compact day.month the report uses in the DATE column."""
    return f"{date.day:02d}.{date.month:02d}"


def format_long_date(date: dt.date, upper: bool = True) -> str:
    """``FRIDAY 14TH AUGUST`` for the section headings, ``Friday 14th August``
    for prose."""
    day = ordinal(date.day) if upper else ordinal(date.day).lower()
    text = f"{date.strftime('%A')} {day} {date.strftime('%B')}"
    return text.upper() if upper else text


def ordinal(day: int) -> str:
    suffix = ("TH" if 11 <= day % 100 <= 13
              else {1: "ST", 2: "ND", 3: "RD"}.get(day % 10, "TH"))
    return f"{day}{suffix}"


#: Country of foaling as the report prints it: "OLD IS GOLD (IRE)".
COUNTRIES = (
    "GB|IRE|FR|USA|GER|ITY|SPA|QA|AUS|NZ|JPN|CAN|SAF|ARG|BRZ|UAE|TUR|"
    "SWE|DEN|NOR|POL|CZE|HUN|SLO|GRE|BEL|SWI|HOL|IND"
)
COUNTRY_SUFFIX = re.compile(rf"\s*\(({COUNTRIES})\)\s*$", re.I)


def clean_horse_name(name: str) -> str:
    """Upper-case the horse and keep the country suffix parenthesised.

    ``Estithmar (FR)`` -> ``ESTITHMAR (FR)``; ``FIRE BULLET IRE`` -> ``FIRE BULLET (IRE)``.
    """
    name = collapse_space(name)
    if not name:
        return ""
    bare = COUNTRY_SUFFIX.sub("", name)
    match = COUNTRY_SUFFIX.search(name)
    suffix = match.group(1).upper() if match else ""
    if not suffix:
        # France Galop appends the country without brackets: "FIRE BULLET IRE".
        trailing = re.search(r"\s+(GB|IRE|FR|USA|GER|ITY|SPA|QA|AUS|NZ|JPN|CAN|SAF|TUR)$", bare)
        if trailing:
            suffix = trailing.group(1)
            bare = bare[: trailing.start()]
    bare = bare.strip().upper()
    return f"{bare} ({suffix})" if suffix else bare


HONORIFICS = re.compile(r"^(mme|mlle|mr?|mrs|ms|miss|dr|sir)\.?\s+", re.I)
PARTICLES = {"de", "van", "von", "der", "den", "du", "la", "le", "di", "da", "of",
             "el", "al", "des", "dos", "ter"}


def clean_pedigree_name(name: str) -> str:
    """Sires and dams are printed without their country code on the report."""
    return title_name(COUNTRY_SUFFIX.sub("", collapse_space(name)))


def title_name(name: str) -> str:
    """Normalise a person's name to title case without mangling ``de`` or ``O'``.

    Continental feeds shout names and jam initials against the surname, so
    ``A.DE MIEULLE`` becomes ``A. De Mieulle`` and ``MME JF. BERNARD`` becomes
    ``JF Bernard``.
    """
    name = collapse_space(name)
    if not name:
        return ""
    # Leave names that already carry mixed case alone -- they are usually right.
    if name != name.upper() and name != name.lower():
        return name
    shouted = name.isupper()
    name = HONORIFICS.sub("", name)
    # Separate an initial that is glued to the next word: "A.DE" -> "A. DE".
    name = re.sub(r"\b([A-Za-z]{1,3})\.(?=[A-Za-z]{2})", r"\1. ", name)
    words = []
    for index, word in enumerate(name.split(" ")):
        if index and word.lower() in PARTICLES:
            words.append(word.lower())
        elif shouted and _is_initials(word):
            # "JF Bernard", "JP Gauvin" -- initials stay capitalised, and a
            # multi-letter group drops its full stop the way the report does.
            letters = word.replace(".", "").upper()
            words.append(letters if len(letters) > 1 else f"{letters}.")
        else:
            words.append(_capitalise_word(word.lower()))
    return collapse_space(" ".join(words))


def _is_initials(word: str) -> bool:
    """``JF``, ``J.F.`` and ``A.`` are initials; ``Ed`` and ``Al`` are not."""
    stripped = word.replace(".", "")
    return 1 <= len(stripped) <= 3 and word.endswith(".") or (
        2 <= len(stripped) <= 3 and stripped.isalpha() and not _has_vowel(stripped))


def _has_vowel(value: str) -> bool:
    return any(letter in "aeiouy" for letter in value.lower())


def _capitalise_word(word: str) -> str:
    for separator in ("-", "'", "."):
        if separator in word:
            return separator.join(_capitalise_word(part) for part in word.split(separator))
    return word[:1].upper() + word[1:]


def strip_owner_prefix(name: str) -> str:
    """Drop honorifics feeds bolt onto owner names before matching."""
    return re.sub(r"^(mr|mrs|ms|miss|dr|sh|sheikh|h\.?e\.?|hh|hrh)\.?\s+", "",
                  collapse_space(name), flags=re.I)


def collapse_space(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("\xa0", " ")).strip()


#: The same course spelt differently across feeds, keyed by the upper-cased
#: variant, so races merge instead of appearing twice.
COURSE_ALIASES = {
    "LA TESTE DE BUCH": "LA TESTE-BASSIN ARCACHON",
    "PARISLONGCHAMP": "PARIS LONGCHAMP",
    # Racing Post still uses the pre-2018 name; France Galop uses the current
    # one. Both reach the same race, so they have to land on one spelling.
    "LONGCHAMP": "PARIS LONGCHAMP",
    "DONOSTIA": "SAN SEBASTIAN",
    "DONOSTIA-SAN SEBASTIAN": "SAN SEBASTIAN",
    # The owner entries page says Epsom, the Sporting Life racecard says Epsom
    # Downs, and both feed the Racing Post adapter -- unaliased, one runner
    # printed as two rows on the same race.
    "EPSOM DOWNS": "EPSOM",
}


def title_course(name: str) -> str:
    """Courses are printed in capitals: ``Yarmouth`` -> ``YARMOUTH``."""
    upper = collapse_space(name).upper()
    return COURSE_ALIASES.get(upper, upper)

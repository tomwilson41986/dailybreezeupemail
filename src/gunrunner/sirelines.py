"""Gun Runner's cross: how his runners do by broodmare sire and by the
broodmare sire's male line (the Gun Runner Mares Report, 441 foals 2019-2024).

A filly's sire becomes her foal's broodmare sire, so a filly is scored on her
own sire: the exact cross where the sample holds it, else his line. Small
samples are pulled toward Gun Runner's 11.1% stakes winners to runners.
"""

from __future__ import annotations

from gunrunner.names import key

BASE = 51 / 457  # Gun Runner stakes winners / runners
PRIOR = 20  # pseudo-runners pulling a small sample to the baseline

# Gun Runner x broodmare sire: (stakes winners, runners)
BMS: dict[str, tuple[int, int]] = {
    "Bernardini": (3, 8),
    "Malibu Moon": (5, 14),
    "Tapit": (10, 52),
    "Harlan's Holiday": (1, 4),
    "Flatter": (1, 4),
    "Mr. Greeley": (1, 5),
    "Pulpit": (1, 5),
    "Street Cry": (1, 6),
    "Curlin": (1, 8),
    "Tiznow": (1, 8),
    "Indian Charlie": (1, 8),
    "Broken Vow": (1, 8),
    "Distorted Humor": (1, 10),
    "Smart Strike": (1, 11),
    "A.P. Indy": (1, 12),
    "Empire Maker": (1, 12),
    "Sky Mesa": (1, 13),
    "Unbridled's Song": (1, 14),
}
# maternal-grandsire male line: (stakes winners, runners)
LINES: dict[str, tuple[int, int]] = {
    "Seattle Slew": (22, 142),
    "In Reality": (2, 12),
    "Storm Cat": (7, 57),
    "Forty Niner": (2, 16),
    "Caro": (2, 17),
    "Fappiano": (5, 61),
    "Sadler's Wells": (1, 12),
    "Mr. Prospector": (3, 50),
    "Gone West": (2, 30),
    "Deputy Minister": (1, 4),
    "Danzig": (1, 3),
    "Majestic Light": (1, 1),
    "Roberto": (0, 6),
    "Ack Ack": (1, 3),
}
LINE_NAME = {
    "Seattle Slew": "Seattle Slew / A.P. Indy",
    "In Reality": "In Reality / Relaunch",
    "Storm Cat": "Storm Bird / Storm Cat",
    "Forty Niner": "Mr. Prospector / Forty Niner",
    "Caro": "Caro / Siberian Express",
    "Fappiano": "Mr. Prospector / Fappiano",
    "Sadler's Wells": "Northern Dancer / Sadler's Wells",
    "Mr. Prospector": "Raise a Native / Mr. Prospector",
    "Gone West": "Mr. Prospector / Gone West",
    "Deputy Minister": "Vice Regent / Deputy Minister",
    "Danzig": "Danzig",
    "Majestic Light": "Majestic Light / Wavering Monarch",
    "Roberto": "Roberto / Kris S.",
    "Ack Ack": "Ack Ack / Broad Brush",
    None: "Other",
}
# Each sire's male line, by his sire's sire (checked by hand; a sire not listed scores at the baseline)
_SIRES_BY_LINE = {
    "Seattle Slew": "Tapit,Constitution,Frosted,Tonalist,Tapiture,Tapizar,Tapwrit,Essential Quality,Tiz the Law,Honor Code,Malibu Moon,Bernardini,Mineshaft,Flatter,Pulpit,Sky Mesa,Congrats,Jump Start,Upstart,West Coast,Dialed In,Algorithms,First Dude,Army Mule,Independence Hall,Orb,A.P. Indy,Lord Nelson,To Honor and Serve,Stay Thirsty,Mohaymen,Cupid,Gormley,Majestic Warrior,Commissioner,Honor A. P.,Take Charge Indy,El Padrino,Race Day,Alpha,Biondetti",
    "Storm Cat": "Into Mischief,Not This Time,Justify,Giant's Causeway,Harlan's Holiday,Practical Joke,Audible,Maximus Mischief,Goldencents,Mitole,Carpe Diem,Shackleford,Tale of Ekati,Girvin,Majesticperfection,No Nay Never,Scat Daddy,Mendelssohn,Sioux Nation,Authentic,Instagrand,Life Is Good,Flameaway,Kantharos,Bucchero,Uncaptured,Sharp Azteca,Karakontie,First Samurai,Lope de Vega,Johannesburg,Hennessy,Tale of the Cat,Bluegrass Cat,Stormy Atlantic,Forestry,Discreet Cat,Storm Cat,Eskendereya,Gio Ponti,Neolithic,Shanghai Bobby,Bernstein,Promises Fulfilled,Cactus Ridge,Lightnin N Thunder,Sweetsouthernsaint,Shamardal,Blue Point,Pinatubo,Earthlight,Caravaggio,Ten Sovereigns,Footstepsinthesand,Epicenter",
    "Forty Niner": "Distorted Humor,Alternation,Maclean's Music,Complexity,Flower Alley,Drosselmeyer,Jimmy Creed,Cloud Computing",
    "Caro": "Uncle Mo,Indian Charlie,Nyquist,Mo Town,Laoban,Caracaro,Yaupon,Outwork,Mo Donegal,Golden Pal,Mizzen Mast,Adios Charlie",
    "Fappiano": "Candy Ride,Twirling Candy,Vekoma,Mastery,Gun Runner,Unbridled's Song,Arrogate,Liam's Map,Will Take Charge,Midshipman,Empire Maker,Pioneerof the Nile,American Pharoah,Cairo Prince,Classic Empire,Bodemeister,Midnight Lute,Broken Vow,Majestic Harbor,Unbridled,Grindstone,Old Fashioned,Cross Traffic,Graydar,First Defence,Mission Impazible,Too Much Bling,Bird Song,Gunite,Taiba,Cave Rock,Cyberknife,Social Inclusion",
    "Sadler's Wells": "Medaglia d'Oro,Bolt d'Oro,Violence,Volatile,Kitten's Joy,Oscar Performance,Galileo,Frankel,Noble Mission,Perfect Soul,Astern,Talismanic,Mshawish,Warrior's Reward,Vancouver,Enticed,Teofilo,New Approach,Churchill,Australia,Nathaniel,Camelot,Gleneagles",
    "Mr. Prospector": "Curlin,Smart Strike,Lookin At Lucky,English Channel,Keen Ice,Vino Rosso,Good Magic,Palace Malice,Connect,Tom's d'Etat,Street Sense,Street Cry,Maxfield,Global Campaign,McKinzie,Lemon Drop Kid,Collected,Improbable,Dubawi,Exaggerator,City Zip,Night of Thunder,Street Boss,Accelerate,Capo Bastone,Run Away and Hide,Kingmambo,King's Best,Dubai Millennium,Postponed,Ghaiyyath,Too Darn Hot,Modern Games,Space Blues,Zarak,Henrythenavigator,Mage",
    "Gone West": "Speightstown,Munnings,Quality Road,Mr. Greeley,City of Light,Jersey Town,Charlatan,Elusive Quality,Central Banker,Speightster,Qurbaan,Raven's Pass,Elusive City,Wootton Bassett,Jack Christopher",
    "In Reality": "Tiznow,Colonel John,Tizway",
    "Deputy Minister": "Ghostzapper,Awesome Again,Paynter,Mucho Macho Man,Awesome Slew,Salt Lake,Oxbow",
    "Danzig": "War Front,Hard Spun,Omaha Beach,The Factor,Declaration of War,War of Will,US Navy Flag,Air Force Blue,Invincible Spirit,Kingman,Kodiac,Jack Milton,Fastnet Rock,Rock of Gibraltar,Power,Starspangledbanner,Bated Breath,Itsmyluckyday,Showcasing,Oasis Dream,Dansili,Danehill,Exceed And Excel,Snitzel,I Am Invincible,Redoute's Choice,Not A Single Doubt,Lawman,Muhaarar,Sea The Stars,Sea The Moon,Native Trail,Shalaa",
    "Majestic Light": "Super Saver,Runhappy,Maria's Mon",
    "Roberto": "Blame,Arch,Instilled Regard,Point of Entry,Dynaformer,Sligo Bay",
    "Ack Ack": "Include,Broad Brush",
}
SIRE_LINE: dict[str, str] = {}
for _line, _sires in _SIRES_BY_LINE.items():
    for _s in _sires.split(","):
        SIRE_LINE.setdefault(key(_s.strip()), _line)
_BMS_BY_KEY = {key(k): (k, v) for k, v in BMS.items()}

# Candy Ride's sons: a daughter of one bred to Gun Runner doubles Candy Ride 2x3
CANDY_RIDE = {key(s) for s in ("Candy Ride", "Twirling Candy", "Vekoma", "Mastery", "Gun Runner")}


def shrunk(sw: int, n: int) -> float:
    return (sw + BASE * PRIOR) / (n + PRIOR)


_LO, _HI = shrunk(3, 50), shrunk(5, 14)  # the weakest line .. Malibu Moon


def line_of(sire: str) -> str | None:
    return SIRE_LINE.get(key(sire))


def pedigree(sire: str, points: float = 25) -> dict:
    """Her sire's rate with Gun Runner: the exact cross where held, else his line,
    else the baseline; scored 0..points between the weakest line and Malibu Moon."""
    k = key(sire)
    line = SIRE_LINE.get(k)
    if k in _BMS_BY_KEY:
        name, (sw, n) = _BMS_BY_KEY[k]
        rate, basis, exact = (
            shrunk(sw, n),
            f"{name} mares x Gun Runner: {sw} SW from {n} runners",
            True,
        )
    elif line:
        sw, n = LINES[line]
        rate, basis, exact = (
            shrunk(sw, n),
            f"{LINE_NAME[line]} line: {sw} SW from {n} runners",
            False,
        )
    else:
        rate, basis, exact = BASE, "Line outside the sample: Gun Runner baseline", False
    pts = max(0.0, min(points, (rate - _LO) / (_HI - _LO) * points))
    return {
        "points": round(pts, 1),
        "rate": rate,
        "basis": basis,
        "exact": exact,
        "line": LINE_NAME[line],
    }

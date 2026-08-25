"""The 14th August report, transcribed from the circulated PDF.

Used as the golden reference for the renderer.
"""

import datetime as dt

from wathnan.models import Breed, Race, Runner, Status
from wathnan.normalise import parse_time

D = dt.date


def _race(day, course, race_type, distance, uk, runners, breed=Breed.THOROUGHBRED,
          status=Status.ENTERED):
    return Race(date=D(2026, 8, day), course=course, race_type=race_type,
                distance_furlongs=distance, off_time_uk=parse_time(uk), breed=breed,
                status=status, runners=tuple(Runner(*r) for r in runners), source="template")


TOMORROW = [
    _race(14, "YARMOUTH", "Class 5 Handicap", 5, "4.25pm",
          [("CREATIVE QUEEN (USA)", "Mitole", "Vigui's Heart", "William Haggas", "Cieren Fallon")],
          status=Status.DECLARED),
    _race(14, "NEWBURY", "Visit Malta St Hugh's Stakes (Listed Race) (Fillies)", 5, "5.23pm",
          [("COSMIC MYSTERY (GB)", "Havana Grey", "Yolo Star", "Archie Watson",
            "Callum Rodriguez")],
          status=Status.DECLARED),
    _race(14, "THIRSK", "Maiden", 6, "5.33pm",
          [("FINAL OBJECTIVE (IRE)", "Sioux Nation", "Sneaky Snooze", "Hamad Al-Jehani",
            "James Doyle")],
          status=Status.DECLARED),
    _race(14, "THIRSK", "Class 4 Handicap", 7, "7.18pm",
          [("ENCHANT (IRE)", "Wootton Bassett", "Sarrocchi", "Karl Burke", "James Doyle")],
          status=Status.DECLARED),
]

ENTRIES = [
    _race(15, "SAN SEBASTIAN", "UAE President Cup Group 3 Arabian", 8, "4.05pm",
          [("CHDIA (FR)", "Al Mourtajez", "Rkaya", "Alban de Mieulle", "Soufiane Saadi")],
          breed=Breed.ARABIAN),
    _race(15, "SAN SEBASTIAN", "58th Copa de Oro de San Sebastián", 12, "6.15pm",
          [("WAFEI (USA)", "American Pharoah", "Flying", "Alban de Mieulle", "Soufiane Saadi")]),
    _race(15, "DEAUVILLE", "Prix de Lieurey Group 3", 8, "3.25pm",
          [("THE PRETTIEST STAR (GB)", "Starman", "Ediyva", "Ed Walker", "James Doyle")]),
    _race(15, "DEAUVILLE", "Prix Gontaut Biron Group 3", 10, "4.00pm",
          [("FIRST LOOK (IRE)", "Lope de Vega", "Bilissie", "André Fabre", "Mickael Barzalona"),
           ("MAP OF STARS (GB)", "Sea The Stars", "Bateel", "Francis-Henri Graffard",
            "James Doyle")]),
    _race(16, "SOUTHWELL", "Class 3 Handicap", 8, "4.10pm",
          [("COLOMBIER (GB)", "Kingman", "Ventoux", "Hamad Al-Jehani", ""),
           ("SKIPPER (GB)", "Calyx", "Skippinish", "Hamad Al-Jehani", ""),
           ("HE'S A MONSTER (IRE)", "No Nay Never", "Al Joza", "Hamad Al-Jehani", ""),
           ("DEFENCE MINISTER (GB)", "Too Darn Hot", "Tears Of The Sun", "Hamad Al-Jehani", "")]),
    _race(16, "SOUTHWELL", "Maiden", 6, "4.40pm",
          [("STORM FORCE (IRE)", "Starspangledbanner", "Southern Belle",
            "Richard & Peter Fahey", "")]),
    _race(18, "WOLVERHAMPTON", "Class 5 Handicap", 6, "7.30pm",
          [("CREATIVE QUEEN (USA)", "Mitole", "Vigui's Heart", "William Haggas", "")]),
    _race(19, "YORK", "Sky Bet Stayers Handicap (Heritage Handicap)", 16.5, "4.10pm",
          [("VALIANCY (IRE)", "Cracksman", "Dromana", "William Haggas", "")]),
    _race(19, "YORK", "Irish Thoroughbred Marketing Handicap (Heritage Handicap)", 5, "4.45pm",
          [("OLD IS GOLD (IRE)", "Mehmas", "Lyons Lane", "Andrew Balding", "")]),
    _race(19, "YORK", "Sky Bet Nursery Handicap Class 2", 6, "5.20pm",
          [("RULER'S PRIDE (IRE)", "Mehmas", "Superiority", "Karl Burke", "")]),
    _race(19, "KEMPTON", "Novice", 7, "7.30pm",
          [("UNITED AUTHORITY (GB)", "Dubawi", "Elizabethofaragon", "Ralph Beckett", "")]),
    _race(19, "KEMPTON", "Class 4 Handicap", 8, "8.30pm",
          [("LE SAMOURAI (IRE)", "New Bay", "Folk Melody", "Ralph Beckett", "")]),
    _race(19, "LA TESTA BA", "Prix De L'Afac PA", 9.5, None,
          [("SHARAH (FR)", "General", "Zilal", "JF Bernard", ""),
           ("NOTABLE DE L'AIGLE (FR)", "Dahess", "No Drug Al Maury", "Francois Rohaut", "")],
          breed=Breed.ARABIAN),
    _race(19, "LA TESTA BA", "Prix Nevadour Group 3 PA", 9.5, None,
          [("DABIDA (FR)", "Divamer", "Adiba", "Alban de Mieulle", "")], breed=Breed.ARABIAN),
    _race(19, "VICHY", "Maiden", 7, None,
          [("MAGNETITE (GB)", "Frankel", "Attraction", "Stephane Wattel", "")]),
]

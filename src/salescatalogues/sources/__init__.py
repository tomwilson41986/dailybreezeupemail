"""Per-auction-house source adapters.

Each module exposes a ``fetch(session=...) -> list[RawSale]`` returning the
upcoming/active sales for one (or, for Tattersalls and Goffs, two) countries,
plus pure ``parse_*`` helpers that run against captured fixtures in tests.

``registry.SOURCES`` is the ordered list the daily job iterates.
"""

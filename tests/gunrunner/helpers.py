from datetime import date

from gunrunner.collect import Candidate


def cand(**kw) -> Candidate:
    base = dict(
        lot_id="keeneland|nov|2026-11:1",
        sale="November Breeding Stock Sale",
        house="Keeneland",
        sale_country="US",
        sale_type="Broodmare",
        sale_date=date(2026, 11, 3),
        sale_url="https://k",
        lot_no="1",
        name="",
        sex="F",
        colour="Bay",
        yob=2025,
        sire="Tapit",
        dam="Route Queen",
        damsire="Tapit",
        vendor="Farm",
        covering_sire="",
        lot_type="",
        breeding_status="",
        ref="",
        url="https://k/1",
    )
    base.update(kw)
    return Candidate(**base)

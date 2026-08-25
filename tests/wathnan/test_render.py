"""The renderer is checked against the circulated 14th August report."""

import datetime as dt

import pdfplumber
import pytest
from template_2026_08_14 import ENTRIES, TOMORROW

from wathnan.render import COL_WIDTHS, LEFT_MARGIN, build_sections, render_report

TOMORROW_DATE = dt.date(2026, 8, 14)
ENTRIES_FROM = dt.date(2026, 8, 15)
ENTRIES_UNTIL = dt.date(2026, 8, 19)


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    path = tmp_path_factory.mktemp("render") / "report.pdf"
    sections = build_sections(TOMORROW, ENTRIES, TOMORROW_DATE, ENTRIES_FROM, ENTRIES_UNTIL)
    return render_report(sections, path)


@pytest.fixture(scope="module")
def pages(report):
    with pdfplumber.open(report) as pdf:
        yield [{"width": page.width, "height": page.height,
                "text": page.extract_text() or "",
                "words": page.extract_words(extra_attrs=["fontname"]),
                "lines": page.lines, "rects": page.rects,
                "images": page.images} for page in pdf.pages]


def test_section_headings_match_the_circulated_wording(pages):
    text = "\n".join(page["text"] for page in pages)
    assert "TOMORROW’S RUNNERS - FRIDAY 14TH AUGUST" in text
    assert "UPDATED ENTRIES SATURDAY 15TH - WEDNESDAY 19TH AUGUST" in text


def test_page_is_us_letter_landscape(pages):
    assert round(pages[0]["width"]), round(pages[0]["height"]) == (792, 612)


def test_branding_appears_on_the_first_page_only(pages):
    assert len(pages[0]["images"]) == 2
    assert all(not page["images"] for page in pages[1:])


def test_column_widths_match_the_template(pages):
    verticals = sorted({round(line["x0"], 1) for line in pages[0]["lines"]
                        if abs(line["x0"] - line["x1"]) < 0.5})
    expected = [LEFT_MARGIN]
    for width in COL_WIDTHS:
        expected.append(expected[-1] + width)
    for boundary in expected:
        assert any(abs(boundary - found) < 1.0 for found in verticals), boundary


def test_header_band_is_the_template_blue(pages):
    """#9FC5E8, the fill the source spreadsheet uses for its header row."""
    fills = [rect["non_stroking_color"] for rect in pages[0]["rects"]
             if rect.get("non_stroking_color")]
    assert any(all(abs(channel - target) < 0.005 for channel, target
                   in zip(fill, (0.6235, 0.7725, 0.9098), strict=False))
               for fill in fills), fills


def test_every_runner_appears(pages):
    text = " ".join(page["text"] for page in pages)
    for race in (*TOMORROW, *ENTRIES):
        for runner in race.runners:
            assert runner.horse.split(" (")[0] in text, runner.horse


def test_horse_names_are_bold_and_arabian_rows_italic(pages):
    fonts = {}
    for page in pages:
        for word in page["words"]:
            fonts.setdefault(word["text"], set()).add(word["fontname"])
    assert any("Bold" in font and "Italic" not in font
               for font in fonts["CREATIVE"]), fonts["CREATIVE"]
    assert any("BoldItalic" in font for font in fonts["CHDIA"]), fonts["CHDIA"]
    # The Arabian runner's sire is italic but not bold.
    assert any("Italic" in font and "Bold" not in font
               for font in fonts["Mourtajez"]), fonts["Mourtajez"]


def test_grouped_cells_are_printed_once(pages):
    text = "\n".join(page["text"] for page in pages)
    assert text.count("16.08") == 1
    assert text.count("SOUTHWELL") == 1


def test_qatar_time_is_two_hours_ahead_in_august(pages):
    text = " ".join(page["text"] for page in pages)
    assert "4.25pm 6.25pm" in text.replace("\n", " ")


def test_missing_times_render_as_tbc(pages):
    text = " ".join(page["text"] for page in pages)
    assert "TBC" in text


def test_report_survives_an_empty_section(tmp_path):
    sections = build_sections([], [], TOMORROW_DATE, ENTRIES_FROM, ENTRIES_UNTIL)
    path = render_report(sections, tmp_path / "empty.pdf")
    assert path.exists() and path.stat().st_size > 1000


def test_logo_asset_is_the_official_brand_gold():
    """The wordmark ships in Wathnan's brand gold (#B69E60), not the black
    copy embedded in the circulated spreadsheet export."""
    from collections import Counter

    from PIL import Image

    from wathnan.render import LOGO

    image = Image.open(LOGO).convert("RGBA")
    opaque = [(r, g, b) for r, g, b, a in image.get_flattened_data() if a > 128]
    assert opaque, "logo has no visible pixels"
    (r, g, b), _count = Counter(opaque).most_common(1)[0]
    assert all(abs(actual - target) <= 8
               for actual, target in zip((r, g, b), (0xB6, 0x9E, 0x60), strict=True)), \
        f"dominant logo colour is #{r:02X}{g:02X}{b:02X}, expected ~#B69E60"

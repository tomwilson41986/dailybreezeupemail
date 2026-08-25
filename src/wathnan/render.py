"""Render the Wathnan runners/entries report as a PDF.

The layout is a faithful reproduction of the circulated spreadsheet export:
US Letter landscape, Wathnan wordmark top left, racing silks top right, two
grouped tables in Roboto Condensed 7pt with a #9FC5E8 header band.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from .config import ASSETS
from .models import Breed, Race, group_rows
from .normalise import format_clock, format_day, format_distance, format_long_date, qatar_time

PAGE_SIZE = landscape(letter)          # 792 x 612pt
PAGE_WIDTH, PAGE_HEIGHT = PAGE_SIZE

LEFT_MARGIN = 70.5
#: Page one leaves room for the wordmark and silks; later pages start higher.
TOP_MARGIN_FIRST = 121.1
TOP_MARGIN_REST = 72.5
BOTTOM_MARGIN = 36.0

HEADER_FILL = colors.Color(0.6235, 0.7725, 0.9098)   # #9FC5E8
GRID_COLOUR = colors.black
GRID_WIDTH = 0.5

COLUMNS = ("DATE", "COURSE", "RACE TYPE", "DISTANCE", "UK TIME", "QATAR TIME",
           "HORSE", "SIRE", "DAM", "TRAINER", "JOCKEY")
COL_WIDTHS = (26.0, 57.0, 129.0, 34.0, 35.0, 41.0, 78.0, 52.0, 48.0, 60.0, 51.0)
TABLE_WIDTH = sum(COL_WIDTHS)
CENTRED_COLUMNS = (3, 4, 5)            # DISTANCE / UK TIME / QATAR TIME

BODY_SIZE = 7.0
BODY_LEADING = 8.2
HEADING_SIZE = 12.0
ROW_MIN_HEIGHT = 21.0
HEADER_ROW_HEIGHT = 16.5
PADDING_LEFT = 3.7
PADDING_RIGHT = 1.5
#: A single-line value may be squeezed by up to this much rather than wrapped,
#: which keeps long course names such as WOLVERHAMPTON on one line.
MAX_SHRINK = 0.95

LOGO = ASSETS / "wathnan-logo.png"
SILKS = ASSETS / "wathnan-silks.png"
FONT_DIR = ASSETS / "fonts"

FONT_REGULAR, FONT_BOLD = "RobotoCondensed", "RobotoCondensed-Bold"
FONT_ITALIC, FONT_BOLD_ITALIC = "RobotoCondensed-Italic", "RobotoCondensed-BoldItalic"


def register_fonts() -> tuple[str, str, str, str]:
    """Register the bundled Roboto Condensed faces, falling back to Helvetica.

    The report is legible either way; the bundled fonts just make it identical
    to the version the team circulates.
    """
    faces = {
        FONT_REGULAR: "RobotoCondensed-Regular.ttf",
        FONT_BOLD: "RobotoCondensed-Bold.ttf",
        FONT_ITALIC: "RobotoCondensed-Italic.ttf",
        FONT_BOLD_ITALIC: "RobotoCondensed-BoldItalic.ttf",
    }
    registered = set(pdfmetrics.getRegisteredFontNames())
    for name, filename in faces.items():
        if name in registered:
            continue
        path = FONT_DIR / filename
        if not path.exists():
            return ("Helvetica", "Helvetica-Bold", "Helvetica-Oblique",
                    "Helvetica-BoldOblique")
        pdfmetrics.registerFont(TTFont(name, str(path)))
    pdfmetrics.registerFontFamily(FONT_REGULAR, normal=FONT_REGULAR, bold=FONT_BOLD,
                                  italic=FONT_ITALIC, boldItalic=FONT_BOLD_ITALIC)
    return FONT_REGULAR, FONT_BOLD, FONT_ITALIC, FONT_BOLD_ITALIC


@dataclass
class Section:
    """One titled table in the report."""

    title: str
    races: Sequence[Race]
    #: Shown in place of the table on a day with nothing to report.
    empty_note: str = "Nothing to report."


class _Styles:
    def __init__(self) -> None:
        regular, bold, italic, bold_italic = register_fonts()
        self.regular_font, self.bold_font = regular, bold
        self.italic_font, self.bold_italic_font = italic, bold_italic
        common = dict(fontSize=BODY_SIZE, leading=BODY_LEADING, textColor=colors.black)
        self.cell = ParagraphStyle("cell", fontName=regular, alignment=TA_LEFT, **common)
        self.cell_centre = ParagraphStyle("cellC", fontName=regular, alignment=TA_CENTER, **common)
        self.cell_bold = ParagraphStyle("cellB", fontName=bold, alignment=TA_LEFT, **common)
        self.cell_italic = ParagraphStyle("cellI", fontName=italic, alignment=TA_LEFT, **common)
        self.cell_bold_italic = ParagraphStyle("cellBI", fontName=bold_italic,
                                               alignment=TA_LEFT, **common)
        self.column_header = ParagraphStyle("colhdr", fontName=bold, alignment=TA_LEFT, **common)
        self.section_title = ParagraphStyle(
            "section", fontName=bold, fontSize=HEADING_SIZE, leading=HEADING_SIZE + 2,
            spaceAfter=0, textColor=colors.black,
            # Never strand a heading at the foot of a page.
            keepWithNext=1,
        )
        self.note = ParagraphStyle("note", fontName=italic, fontSize=7, leading=9,
                                   textColor=colors.Color(0.35, 0.35, 0.35))


def _escape(value: str) -> str:
    return (value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _cell(text: str, style: ParagraphStyle, column: int) -> Paragraph:
    """Build a cell, shrinking a hair rather than wrapping a near-fit value."""
    text = (text or "").strip()
    if not text:
        return Paragraph("", style)
    available = COL_WIDTHS[column] - PADDING_LEFT - PADDING_RIGHT
    width = pdfmetrics.stringWidth(text, style.fontName, style.fontSize)
    if available < width <= available / MAX_SHRINK:
        scale = available / width
        style = ParagraphStyle(f"{style.name}-fit", parent=style,
                               fontSize=style.fontSize * scale)
    return Paragraph(_escape(text), style)


def _build_rows(styles: _Styles, races: Sequence[Race]) -> list[list[Paragraph]]:
    header = [_cell(name, styles.column_header, index) for index, name in enumerate(COLUMNS)]
    rows = [header]
    for race, runner, show in group_rows(races):
        arabian = race.breed is Breed.ARABIAN
        horse_style = styles.cell_bold_italic if arabian else styles.cell_bold
        detail_style = styles.cell_italic if arabian else styles.cell
        uk = race.off_time_uk
        rows.append([
            _cell(format_day(race.date) if show["date"] else "", styles.cell, 0),
            _cell(race.course if show["course"] else "", styles.cell, 1),
            _cell(race.race_type if show["race"] else "", styles.cell, 2),
            _cell(format_distance(race.distance_furlongs) if show["race"] else "",
                  styles.cell_centre, 3),
            _cell(format_clock(uk) if show["race"] else "", styles.cell_centre, 4),
            _cell(format_clock(qatar_time(uk, race.date)) if show["race"] else "",
                  styles.cell_centre, 5),
            _cell(runner.horse, horse_style, 6),
            _cell(runner.sire, detail_style, 7),
            _cell(runner.dam, detail_style, 8),
            _cell(runner.trainer, detail_style, 9),
            _cell(runner.display_jockey(), detail_style, 10),
        ])
    return rows


def _table_style() -> TableStyle:
    return TableStyle([
        ("GRID", (0, 0), (-1, -1), GRID_WIDTH, GRID_COLOUR),
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_FILL),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), PADDING_LEFT),
        ("RIGHTPADDING", (0, 0), (-1, -1), PADDING_RIGHT),
        ("TOPPADDING", (0, 0), (-1, -1), 2.0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.0),
        # The three numeric columns are centred, everything else is flush left.
        ("ALIGN", (3, 0), (5, -1), "CENTER"),
    ])


def _build_table(styles: _Styles, races: Sequence[Race]) -> Table:
    rows = _build_rows(styles, races)
    heights = [HEADER_ROW_HEIGHT] + [None] * (len(rows) - 1)
    table = Table(rows, colWidths=list(COL_WIDTHS), rowHeights=heights,
                  repeatRows=0, hAlign="LEFT")
    table.setStyle(_table_style())
    return table


class _ReportDoc(BaseDocTemplate):
    """Draws the branding on page one and lays every page out in one frame."""

    def __init__(self, path: Path, subtitle: str) -> None:
        super().__init__(
            str(path), pagesize=PAGE_SIZE,
            leftMargin=LEFT_MARGIN, rightMargin=PAGE_WIDTH - LEFT_MARGIN - TABLE_WIDTH,
            topMargin=TOP_MARGIN_FIRST, bottomMargin=BOTTOM_MARGIN,
            title=subtitle, author="Wathnan Racing", subject=subtitle,
            creator="wathnan-racing-report",
        )
        first_frame = Frame(
            LEFT_MARGIN, BOTTOM_MARGIN, TABLE_WIDTH,
            PAGE_HEIGHT - TOP_MARGIN_FIRST - BOTTOM_MARGIN,
            leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id="first",
        )
        rest_frame = Frame(
            LEFT_MARGIN, BOTTOM_MARGIN, TABLE_WIDTH,
            PAGE_HEIGHT - TOP_MARGIN_REST - BOTTOM_MARGIN,
            leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id="rest",
        )
        self.addPageTemplates([
            PageTemplate(id="first", frames=[first_frame], onPage=self._draw_branding),
            PageTemplate(id="rest", frames=[rest_frame]),
        ])

    @staticmethod
    def _draw_branding(canvas, _doc) -> None:
        canvas.saveState()
        if LOGO.exists():
            canvas.drawImage(str(LOGO), 9.0, PAGE_HEIGHT - 97.5, width=123.75, height=88.5,
                             mask="auto", preserveAspectRatio=True, anchor="sw")
        if SILKS.exists():
            canvas.drawImage(str(SILKS), 679.5, PAGE_HEIGHT - 87.75, width=111.0, height=78.75,
                             mask="auto", preserveAspectRatio=True, anchor="se")
        canvas.restoreState()

    def afterFlowable(self, flowable) -> None:  # noqa: D102 - reportlab hook
        pass

    def handle_pageBegin(self) -> None:  # noqa: N802 - reportlab hook
        super().handle_pageBegin()
        self._handle_nextPageTemplate("rest")


def render_report(sections: Sequence[Section], path: Path,
                  notes: Sequence[str] = ()) -> Path:
    """Write the report to ``path`` and return it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    styles = _Styles()
    doc = _ReportDoc(path, sections[0].title if sections else "Wathnan Racing")

    story: list = []
    for index, section in enumerate(sections):
        if index:
            story.append(Spacer(1, 30.3))
        story.append(Paragraph(_escape(section.title), styles.section_title))
        story.append(Spacer(1, 18.8 - 2))
        if section.races:
            story.append(_build_table(styles, section.races))
        else:
            story.append(Paragraph(_escape(section.empty_note), styles.cell))
    if notes:
        story.append(Spacer(1, 14))
        for note in notes:
            story.append(Paragraph(_escape(note), styles.note))

    doc.build(story)
    return path


def build_sections(tomorrow_races: Sequence[Race], entry_races: Sequence[Race],
                   tomorrow: dt.date, entries_from: dt.date,
                   entries_until: dt.date) -> list[Section]:
    """Title the two tables exactly as the circulated report does."""
    first = f"TOMORROW\u2019S RUNNERS - {format_long_date(tomorrow)}"
    from_label = f"{entries_from.strftime('%A')} {_ordinal_only(entries_from)}".upper()
    second = (f"UPDATED ENTRIES {from_label} - {format_long_date(entries_until)}")
    return [
        Section(first, tomorrow_races, empty_note="No runners declared."),
        Section(second, entry_races, empty_note="No entries."),
    ]


def _ordinal_only(date: dt.date) -> str:
    from .normalise import ordinal
    return ordinal(date.day)

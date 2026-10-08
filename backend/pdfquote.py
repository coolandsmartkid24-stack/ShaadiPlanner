"""The quotation PDF (reportlab).  Same document the wizard previews on the Send step:
logo and wordmark top-left, title and date top-right, then the details table, the menu and
the reply line.  Every piece of text the user typed goes through escape() and a wrapping
Paragraph, so a long note can never run off the page."""
import math
from datetime import date
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

import quotations as qdb

INK = colors.HexColor("#0d0b12")
MUTED = colors.HexColor("#6c6877")
HAIR = colors.HexColor("#c9c5d4")

P = lambda **kw: ParagraphStyle(**kw)
TITLE = P(name="title", fontName="Helvetica-Bold", fontSize=17, leading=20, textColor=INK)
DATE_L = P(name="date", fontName="Helvetica", fontSize=9, leading=12, textColor=MUTED)
LABEL = P(name="label", fontName="Helvetica-Bold", fontSize=7.5, leading=10, textColor=MUTED,
          spaceBefore=11, spaceAfter=1)
VALUE = P(name="value", fontName="Helvetica-Bold", fontSize=10.5, leading=14, textColor=INK)
BODY = P(name="body", fontName="Helvetica", fontSize=10.5, leading=15.5, textColor=INK, spaceBefore=10)
CELL = P(name="cell", fontName="Helvetica", fontSize=10, leading=13.5, textColor=INK)
CELL_B = P(name="cellb", fontName="Helvetica-Bold", fontSize=10, leading=13.5, textColor=INK)
RIGHT = P(name="right", fontName="Helvetica-Bold", fontSize=10, leading=13.5, textColor=INK,
          alignment=2)
MENU_ITEM = P(name="menu", fontName="Helvetica", fontSize=10, leading=15, textColor=INK)


def _star(c, cx, cy, r):
    p = c.beginPath()
    for i in range(10):
        a = math.pi / 2 + i * math.pi / 5
        rad = r if i % 2 == 0 else r * 0.44
        x, y = cx + rad * math.cos(a), cy + rad * math.sin(a)
        (p.moveTo if i == 0 else p.lineTo)(x, y)
    p.close()
    return p


class Logo(Flowable):
    """The app mark for print: black rounded square, white star, then Shaadi Planner."""

    def __init__(self, size=28, width=170):
        Flowable.__init__(self)
        self.size, self.width, self.height = size, width, size

    def draw(self):
        c, s = self.canv, self.size
        c.setFillColor(INK)
        c.roundRect(0, 0, s, s, s * 0.3, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.drawPath(_star(c, s / 2, s / 2, s * 0.32), stroke=0, fill=1)
        c.setFont("Helvetica-Bold", 14)
        c.setFillColor(INK)
        x = s + 9
        c.drawString(x, s * 0.3, "Shaadi")
        x += c.stringWidth("Shaadi", "Helvetica-Bold", 14)
        c.setFillColor(MUTED)
        c.drawString(x, s * 0.3, " Planner")


def _header(q):
    right = [Paragraph("Quotation Request", TITLE),
             Paragraph(date.today().strftime("%d %b %Y"), DATE_L)]
    t = Table([[Logo(), right]], colWidths=[240, 240])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                           ("TOPPADDING", (0, 0), (-1, -1), 0),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return t


def _details(q, width):
    rows = [
        ("Event", q["event_type"] + (f" · {q['title']}" if q["title"] else "")),
        ("Date and day", qdb.nice_date(q["event_date"]) + (f" · {qdb.day_name(q['event_date'])}" if q["event_date"] else "")),
        ("Time", f"{q['slot']} · {q['time']}"),
        ("Number of persons", qdb.group(q["guests"])),
    ]
    t = Table([[Paragraph(escape(a), CELL), Paragraph(escape(b), RIGHT)] for a, b in rows],
              colWidths=[width * 0.45, width * 0.55])
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1, INK),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, HAIR),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return t


def _menu(items, width):
    cells = [Paragraph("·  " + escape(d), MENU_ITEM) for d in items]   # "•" is not in Helvetica's
                                                                       # WinAnsi set - a middot is
    if not cells:
        return [Paragraph("Not decided yet", VALUE)]
    if len(cells) % 2:
        cells.append("")
    t = Table([list(r) for r in zip(cells[::2], cells[1::2])], colWidths=[width / 2, width / 2])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                           ("TOPPADDING", (0, 0), (-1, -1), 2),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    return [t]


def quotation_pdf(q, hall, user):
    """-> PDF bytes for one quotation.  `hall` is the venue it is prepared for (may be None yet)."""
    width = A4[0] - 88
    host = q["host"] or user.get("name") or ""
    phone = user.get("phone") or ""
    day = qdb.day_name(q["event_date"]) or "day"
    intro = (f"Assalam o Alaikum. I would like a quotation for my {q['event_type'].lower()} at your "
             f"venue on {qdb.nice_date(q['event_date'])} ({day}, {q['slot'].lower()}, {q['time']}). "
             f"Kindly see the details below and let us know your price and availability.")
    story = [
        _header(q),
        Spacer(1, 18),
        Paragraph("Prepared for", LABEL),
        Paragraph(escape(hall["name"] if hall else "Your chosen hall"), VALUE),
        Paragraph("From", LABEL),
        Paragraph(escape(f"{host} · {phone}" if phone else host), VALUE),
        Paragraph(escape(intro), BODY),
        Spacer(1, 10),
        Paragraph("Details", LABEL),
        Spacer(1, 3),
        _details(q, width),
        Paragraph("Services wanted", LABEL),
        Paragraph(escape(", ".join(q["services"]) or "None selected"), VALUE),
        Paragraph("Food menu", LABEL),
        Spacer(1, 3),
        *_menu(q["menu"], width),
    ]
    if q["notes"]:
        story += [Paragraph("Notes", LABEL), Paragraph(escape(q["notes"]), VALUE)]
    story += [Spacer(1, 16)]

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=44, rightMargin=44, topMargin=40, bottomMargin=44,
                            title="Quotation Request", author="Shaadi Planner")
    doc.build(story)
    return buf.getvalue()

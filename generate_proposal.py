#!/usr/bin/env python3
"""
generate_proposal.py — One-page WebByMaya website proposal PDF.

Requires: fpdf2  (pip install fpdf2)

USAGE — standalone
    python3 generate_proposal.py --name "Bloom Florist"
    python3 generate_proposal.py --name "Bloom Florist" --mockup-url "https://..."
    python3 generate_proposal.py --name "Bloom Florist" --rating 4.8 --reviews 62

USAGE — imported
    from generate_proposal import make_proposal
    pdf_path = make_proposal("Bloom Florist", mockup_url="https://...", rating="4.8", review_count="62")
"""

import argparse
import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

# Map of Unicode code points -> Latin-1 safe substitutions (all numeric, no Unicode in source)
_CHAR_MAP = {
    0x2014: "--",  # em dash
    0x2013: "-",   # en dash
    0x2018: "'",   # left single curly quote
    0x2019: "'",   # right single curly quote
    0x201C: '"',   # left double curly quote
    0x201D: '"',   # right double curly quote
    0x2022: "+",   # bullet
    0x2026: "...", # ellipsis
    0x2713: "+",   # check mark
    0x2714: "+",   # heavy check mark
    0x00B7: ".",   # middle dot
}

def _s(text: str) -> str:
    """Substitute non-Latin-1 chars so fpdf2 core fonts can render the text."""
    out = []
    for c in text:
        cp = ord(c)
        if cp in _CHAR_MAP:
            out.append(_CHAR_MAP[cp])
        elif cp < 256:
            out.append(c)
        # else: drop — not representable in Latin-1
    return "".join(out)


# Brand palette
GOLD   = (201, 169, 110)   # #C9A96E
DARK   = ( 13,  13,  13)   # #0d0d0d
WHITE  = (255, 255, 255)
BODY   = ( 51,  51,  51)   # #333333
MID    = (120, 120, 120)
LIGHT  = (245, 245, 245)   # #f5f5f5
BORDER = (220, 220, 220)


def _fill(pdf, r, g, b):
    pdf.set_fill_color(r, g, b)

def _text(pdf, r, g, b):
    pdf.set_text_color(r, g, b)

def _draw(pdf, r, g, b):
    pdf.set_draw_color(r, g, b)


def make_proposal(
    business_name: str,
    category:      str = "",
    mockup_url:    str = "",
    rating:        str = "",
    review_count:  str = "",
    output_dir:    Path = None,
) -> Path:
    """Generate proposal PDF. Returns the output path."""
    try:
        from fpdf import FPDF
    except ImportError:
        raise RuntimeError("fpdf2 not installed — run: pip install fpdf2")

    output_dir = output_dir or SCRIPT_DIR / "proposals"
    output_dir.mkdir(parents=True, exist_ok=True)

    slug = "".join(c if c.isalnum() else "-" for c in business_name.lower()).strip("-")
    out  = output_dir / f"proposal-{slug}.pdf"

    today = datetime.date.today().strftime("%B %d, %Y")

    pdf = FPDF(orientation="P", unit="mm", format="Letter")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(0, 0, 0)
    pdf.add_page()

    W = pdf.w      # 215.9 mm
    PAD = 20       # side padding
    CW  = W - PAD * 2    # content width

    # ── HEADER (dark band) ────────────────────────────────────────────────────
    HEADER_H = 52
    _fill(pdf, *DARK)
    _draw(pdf, *DARK)
    pdf.rect(0, 0, W, HEADER_H, "F")

    # Logo — left
    _text(pdf, *GOLD)
    pdf.set_font("Helvetica", "B", 26)
    pdf.set_xy(PAD, 12)
    pdf.cell(0, 10, "WebByMaya", align="L")

    _text(pdf, *MID)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_xy(PAD, 24)
    pdf.cell(0, 5, "Philadelphia Web Design", align="L")

    # Title — right
    _text(pdf, *WHITE)
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_xy(0, 12)
    pdf.cell(W - PAD, 10, "Website Proposal", align="R")

    _text(pdf, *GOLD)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_xy(0, 24)
    pdf.cell(W - PAD, 5, f"Prepared for: {business_name}", align="R")

    _text(pdf, *MID)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_xy(0, 30)
    pdf.cell(W - PAD, 5, today, align="R")

    # Gold separator
    _draw(pdf, *GOLD)
    pdf.set_line_width(0.8)
    pdf.line(PAD, HEADER_H, W - PAD, HEADER_H)
    pdf.set_line_width(0.2)

    Y = HEADER_H + 10

    # ── MOCKUP PREVIEW CARD ───────────────────────────────────────────────────
    if mockup_url:
        _fill(pdf, *DARK)
        _draw(pdf, *DARK)
        pdf.rect(PAD, Y, CW, 26, "F")

        _text(pdf, *GOLD)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_xy(PAD, Y + 4)
        pdf.cell(CW, 5, "YOUR FREE WEBSITE PREVIEW", align="C")

        _fill(pdf, *GOLD)
        _draw(pdf, *GOLD)
        pdf.rect(PAD + 30, Y + 10, CW - 60, 10, "F")
        _text(pdf, *DARK)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_xy(PAD + 30, Y + 11)
        pdf.cell(CW - 60, 8, "View Your Preview ->", align="C", link=mockup_url)

        _text(pdf, *MID)
        pdf.set_font("Helvetica", "", 7)
        pdf.set_xy(PAD, Y + 22)
        pdf.cell(CW, 4, mockup_url[:80], align="C")

        Y += 32

    # ── INTRO PITCH ───────────────────────────────────────────────────────────
    _text(pdf, *BODY)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_xy(PAD, Y)

    pitch = _s(
        f"I noticed {business_name} doesn't have a website yet. Right now, anyone "
        f"searching online can't find you -- no hours, no location, no way to reach you. "
        f"A professional website changes that immediately."
    )
    if rating:
        try:
            r  = float(rating)
            rc = int(review_count) if review_count else 0
            if r >= 4.0:
                pitch += _s(
                    f" With a {r:g}-star rating"
                    + (f" and {rc} reviews" if rc else "")
                    + ", you've already built great word-of-mouth -- a website will bring you online customers too."
                )
        except (ValueError, TypeError):
            pass

    pdf.multi_cell(CW, 5, _s(pitch), align="L")
    Y = pdf.get_y() + 6

    # ── PACKAGES ──────────────────────────────────────────────────────────────
    _text(pdf, *DARK)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_xy(PAD, Y)
    pdf.cell(CW, 6, "Packages", align="L")
    Y += 8

    BOX_W = (CW - 9) / 4   # 4 boxes with 3mm gap between them
    BOXES = [
        {
            "title":    "Lite",
            "price":    "$499",
            "bullets":  ["1 page — key info,", "clean & professional", "Mobile-ready"],
            "highlight":"Live in 1 week",
            "plan":     "$150 now + $349 launch",
            "featured": False,
        },
        {
            "title":    "Starter",
            "price":    "$799",
            "bullets":  ["5 pages (Home, About,", "Services, Gallery, Contact)", "Mobile-ready & Analytics"],
            "highlight":"Live in 2 weeks",
            "plan":     "$200 now + $599 launch",
            "featured": True,
        },
        {
            "title":    "Standard",
            "price":    "$1,299",
            "bullets":  ["8 pages + quote form", "On-page SEO", "Online booking"],
            "highlight":"Live in 3 weeks",
            "plan":     "$300 now + $999 launch",
            "featured": False,
        },
        {
            "title":    "Custom",
            "price":    "$1,999+",
            "bullets":  ["Fully custom design", "E-commerce / menus", "Timeline by scope"],
            "highlight":"Timeline discussed",
            "plan":     "",
            "featured": False,
        },
    ]

    BOX_H = 62
    for idx, box in enumerate(BOXES):
        bx = PAD + idx * (BOX_W + 3)  # noqa
        by = Y

        # Box border
        if box["featured"]:
            _draw(pdf, *GOLD)
            pdf.set_line_width(0.6)
        else:
            _draw(pdf, *BORDER)
            pdf.set_line_width(0.3)
        _fill(pdf, 255, 255, 255)
        pdf.rect(bx, by, BOX_W, BOX_H, "FD")
        pdf.set_line_width(0.2)

        # "Most Popular" badge
        if box["featured"]:
            _fill(pdf, *GOLD)
            _draw(pdf, *GOLD)
            pdf.rect(bx + 6, by - 3.5, BOX_W - 12, 7, "F")
            _text(pdf, *DARK)
            pdf.set_font("Helvetica", "B", 7)
            pdf.set_xy(bx + 6, by - 3)
            pdf.cell(BOX_W - 12, 5, "MOST POPULAR", align="C")

        # Title
        _text(pdf, *DARK)
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_xy(bx + 3, by + 4)
        pdf.cell(BOX_W - 6, 6, box["title"], align="L")

        # Price
        _text(pdf, *GOLD)
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_xy(bx + 3, by + 11)
        pdf.cell(BOX_W - 6, 7, box["price"], align="L")

        # Bullets
        _text(pdf, *BODY)
        pdf.set_font("Helvetica", "", 8)
        bullet_y = by + 20
        for b in box["bullets"]:
            pdf.set_xy(bx + 4, bullet_y)
            pdf.cell(BOX_W - 8, 4, f"- {_s(b)}", align="L")
            bullet_y += 4.2

        # Highlight (timeline)
        _text(pdf, *GOLD)
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_xy(bx + 3, by + BOX_H - 14)
        pdf.cell(BOX_W - 6, 5, box["highlight"], align="L")

        # Payment plan note
        if box.get("plan"):
            _text(pdf, 120, 100, 60)
            pdf.set_font("Helvetica", "I", 6.5)
            pdf.set_xy(bx + 3, by + BOX_H - 8)
            pdf.cell(BOX_W - 6, 4, box["plan"], align="L")

    Y += BOX_H + 8

    # ── INCLUDED IN ALL PACKAGES ──────────────────────────────────────────────
    _fill(pdf, *LIGHT)
    _draw(pdf, *LIGHT)
    pdf.rect(PAD, Y, CW, 11, "F")
    _text(pdf, *DARK)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_xy(PAD + 3, Y + 1)
    pdf.cell(30, 5, "All packages include:", align="L")
    _text(pdf, *BODY)
    pdf.set_font("Helvetica", "", 9)
    items = ["1-year free hosting", "SSL certificate", "Domain setup", "30-day support"]
    x_cursor = PAD + 42
    for item in items:
        _text(pdf, *GOLD)
        pdf.set_xy(x_cursor, Y + 1)
        pdf.cell(4, 5, "+", align="L")
        _text(pdf, *BODY)
        pdf.set_xy(x_cursor + 4, Y + 1)
        pdf.cell(32, 5, item, align="L")
        x_cursor += 36

    Y += 17

    # ── TIMELINE ──────────────────────────────────────────────────────────────
    _text(pdf, *DARK)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_xy(PAD, Y)
    pdf.cell(CW, 6, "How It Works", align="L")
    Y += 8

    steps = [
        ("1", "Fill out\nmy form"),
        ("2", "Mockup\nin 48h"),
        ("3", "You\napprove"),
        ("4", "Go live\nin 7 days"),
    ]
    STEP_W = CW / len(steps)
    for i, (num, label) in enumerate(steps):
        sx = PAD + i * STEP_W + STEP_W / 2

        # Circle
        _fill(pdf, *GOLD)
        _draw(pdf, *GOLD)
        pdf.circle(sx, Y + 4, 4, "F")
        _text(pdf, *DARK)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_xy(sx - 3, Y + 1)
        pdf.cell(6, 6, num, align="C")

        # Label (2 lines)
        _text(pdf, *BODY)
        pdf.set_font("Helvetica", "", 8)
        lines = label.split("\n")
        for li, line in enumerate(lines):
            pdf.set_xy(PAD + i * STEP_W, Y + 9 + li * 4)
            pdf.cell(STEP_W, 4, line, align="C")

        # Arrow between steps
        if i < len(steps) - 1:
            _text(pdf, *GOLD)
            pdf.set_font("Helvetica", "B", 12)
            pdf.set_xy(PAD + (i + 1) * STEP_W - 8, Y + 1)
            pdf.cell(8, 6, ">", align="R")

    Y += 24

    # ── MAINTENANCE PLANS ────────────────────────────────────────────────────
    _text(pdf, *DARK)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_xy(PAD, Y)
    pdf.cell(CW, 6, "Optional: Monthly Care Plans", align="L")
    Y += 8

    PLANS = [
        {"name": "Hosting",  "price": "$29/mo",  "note": "Hosting + SSL renewal. Site stays live."},
        {"name": "Updates",  "price": "$79/mo",  "note": "Monthly content edits, uptime monitoring."},
        {"name": "Growth",   "price": "$149/mo", "note": "SEO report + Google Ads management."},
    ]
    PLAN_W = (CW - 4) / 3
    for idx, plan in enumerate(PLANS):
        px = PAD + idx * (PLAN_W + 2)
        _fill(pdf, 248, 248, 248)
        _draw(pdf, *BORDER)
        pdf.set_line_width(0.2)
        pdf.rect(px, Y, PLAN_W, 16, "FD")
        _text(pdf, *DARK)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_xy(px + 2, Y + 2)
        pdf.cell(PLAN_W - 4, 4, plan["name"], align="L")
        _text(pdf, *GOLD)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_xy(px + 2, Y + 6)
        pdf.cell(PLAN_W - 4, 4, plan["price"], align="L")
        _text(pdf, *MID)
        pdf.set_font("Helvetica", "", 7)
        pdf.set_xy(px + 2, Y + 11)
        pdf.cell(PLAN_W - 4, 3, _s(plan["note"]), align="L")

    Y += 22

    # ── CTA BAND ─────────────────────────────────────────────────────────────
    _fill(pdf, *DARK)
    _draw(pdf, *DARK)
    pdf.rect(PAD, Y, CW, 28, "F")

    _text(pdf, *GOLD)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_xy(PAD, Y + 5)
    pdf.cell(CW, 7, "Ready to get started?", align="C")

    _text(pdf, *WHITE)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_xy(PAD, Y + 13)
    pdf.cell(CW, 5, "Fill out my intake form at  webbymaya.com/book", align="C")

    _text(pdf, *MID)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_xy(PAD, Y + 19)
    pdf.cell(CW, 5, "No calls needed  ·  I build from your answers  ·  Reply here with any questions", align="C")

    Y += 34

    # ── FOOTER ───────────────────────────────────────────────────────────────
    _fill(pdf, *DARK)
    _draw(pdf, *DARK)
    pdf.rect(0, Y, W, 14, "F")
    _text(pdf, *MID)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_xy(PAD, Y + 3)
    footer = "Maya Sierra  ·  Web Designer  ·  WebByMaya.com  ·  maya@webbymaya.com  ·  Philadelphia, PA"
    pdf.cell(CW, 5, footer, align="C")

    pdf.output(str(out))
    return out


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--name",        required=True, help="Business name")
    p.add_argument("--category",    default="")
    p.add_argument("--mockup-url",  default="", dest="mockup_url")
    p.add_argument("--rating",      default="")
    p.add_argument("--reviews",     default="", dest="review_count")
    p.add_argument("--out",         default="", help="Output directory")
    args = p.parse_args()

    out_dir = Path(args.out) if args.out else None
    path = make_proposal(
        business_name=args.name,
        category=args.category,
        mockup_url=args.mockup_url,
        rating=args.rating,
        review_count=args.review_count,
        output_dir=out_dir,
    )
    print(f"Proposal saved: {path}")


if __name__ == "__main__":
    main()

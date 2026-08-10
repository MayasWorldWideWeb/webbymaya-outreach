#!/usr/bin/env python3
"""Build a daily phone-call list of no-website businesses, with a sellable
preview site already built for each one.

Phone is the channel that actually reaches these prospects: ~73% have a phone,
only ~8% have a usable email. This picks the best N leads for a given day,
generates a live mockup for each, and writes a call sheet you can work through.

  python3 call_list.py                      # tomorrow, 10 leads, lunch window
  python3 call_list.py --date 2026-08-04 --count 10
  python3 call_list.py --window any         # allow restaurants/cafes
  python3 call_list.py --no-mockups         # fast dry run, no preview build

Leads already queued on a previous day never come back (.call_state.json).
Log outcomes in the generated CSV; `--outcomes` prints a running tally.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import glob
import html
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
STATE_FILE = SCRIPT_DIR / ".call_state.json"
SHEET_DIR = SCRIPT_DIR / "call_sheets"
# Hand-verified results: the scrapers' has_website flag is wrong often enough
# that a lead saying "you have no website" to someone who has one burns the
# call in the first ten seconds. Rows marked has_site=yes never get picked.
VERIFIED_FILE = SCRIPT_DIR / "verified_sites.csv"

sys.path.insert(0, str(SCRIPT_DIR))

try:
    from find_prospects import CHAIN_KEYWORDS
except Exception:                                    # pragma: no cover
    CHAIN_KEYWORDS = {"mcdonald", "starbucks", "dunkin", "great clips", "cvs"}

try:
    import offer
    PRICE = offer.PRICE
    MONTHLY = getattr(offer, "MONTHLY", "$29/mo")
except Exception:                                    # pragma: no cover
    PRICE, MONTHLY = "$499", "$29/mo"

# Categories worth calling between 11:30 and 1:30. Food service is excluded by
# default — lunch rush is the single worst time to reach a restaurant owner.
LUNCH_OK = {
    "auto repair", "hair salon", "nail salon", "barbershop", "beauty salon",
    "cleaning service", "landscaping", "photographer", "florist", "massage",
    "spa", "gym", "tattoo parlor", "pet grooming", "pet store", "towing",
    "hvac", "plumber", "electrician", "roofing", "contractor", "daycare",
    "childcare", "tailor", "dry cleaner", "print shop", "moving company",
}
FOOD = {"restaurant", "cafe", "bakery", "deli", "pizzeria", "food truck",
        "caterer", "coffee shop", "juice bar", "ice cream"}

# A business with reviews is a business that already cares how it looks.
MIN_REVIEWS = 5
MIN_RATING = 4.0


def norm_phone(raw: str) -> str:
    d = re.sub(r"\D", "", raw or "")
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    return d if len(d) == 10 else ""


def pretty_phone(d: str) -> str:
    return f"({d[:3]}) {d[3:6]}-{d[6:]}" if len(d) == 10 else d


def is_chain(name: str) -> bool:
    low = (name or "").lower()
    return any(k in low for k in CHAIN_KEYWORDS)


def clean_name(raw: str) -> str:
    """Prospect names carry stray search-highlight markup from the scrapers."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", raw or "")).strip()


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"queued": {}}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=1))


def load_verified() -> dict:
    """phone -> {'has_site': 'yes'|'no', 'site': url, 'note': str}"""
    out = {}
    if VERIFIED_FILE.exists():
        for row in csv.DictReader(open(VERIFIED_FILE, encoding="utf-8", errors="ignore")):
            p = norm_phone(row.get("phone", ""))
            if p:
                out[p] = row
    return out


def load_suppressed_phones() -> set:
    """Anyone who texted STOP does not get a sales call either."""
    out = set()
    f = SCRIPT_DIR / "bounce_log.csv"
    if f.exists():
        for row in csv.DictReader(open(f, encoding="utf-8", errors="ignore")):
            p = norm_phone(row.get("phone", ""))
            if p:
                out.add(p)
    return out


def load_emailed_names() -> dict:
    """name(lower) -> last date we emailed them, so the call can reference it."""
    out = {}
    for path in sorted(glob.glob(str(SCRIPT_DIR / "send_log_*.csv"))):
        try:
            for row in csv.DictReader(open(path, encoding="utf-8", errors="ignore")):
                if (row.get("status") or "").lower().startswith("sent"):
                    nm = clean_name(row.get("name", "")).lower()
                    if nm:
                        out[nm] = (row.get("timestamp") or "")[:10]
        except Exception:
            continue
    return out


def load_prospects() -> list:
    rows, seen = [], set()
    for path in sorted(glob.glob(str(SCRIPT_DIR / "prospects_*.csv")), reverse=True):
        try:
            for r in csv.DictReader(open(path, encoding="utf-8", errors="ignore")):
                phone = norm_phone(r.get("phone", ""))
                name = clean_name(r.get("name", ""))
                if not phone or not name:
                    continue
                key = (phone, name.lower())
                if key in seen:
                    continue
                seen.add(key)
                r["_phone"] = phone
                r["_name"] = name
                rows.append(r)
        except Exception:
            continue
    return rows


def score(row: dict, city_filter: str) -> float:
    s = 0.0
    try:
        reviews = int(float(row.get("review_count") or 0))
    except ValueError:
        reviews = 0
    try:
        rating = float(row.get("rating") or 0)
    except ValueError:
        rating = 0.0

    # Established + well-liked + invisible online = the whole pitch in one lead.
    s += min(reviews, 200) * 0.2
    s += (rating - 3.5) * 20 if rating else 0
    if row.get("_verified"):
        s += 60                              # hand-checked: really has no site
    if "phl-licenses" in (row.get("notes") or ""):
        s += 40                              # brand-new business, no site yet
    city = (row.get("city") or "").lower()
    if city_filter and city_filter.lower() in city:
        s += 25
    if (row.get("website_status") or "").lower() in ("dead", "none"):
        s += 5
    return s


def pick(count: int, window: str, city_filter: str, state: dict,
         verified_only: bool = False) -> list:
    suppressed = load_suppressed_phones()
    verified = load_verified()
    already = set(state.get("queued", {}))
    rows = load_prospects()

    picks, used_names = [], set()
    scored = []
    for r in rows:
        if r["_phone"] in already or r["_phone"] in suppressed:
            continue
        v = verified.get(r["_phone"])
        if v and (v.get("has_site") or "").strip().lower() == "yes":
            continue                          # confirmed to already have a site
        if verified_only and not v:
            continue
        if v:
            r["_verified"] = v
        if is_chain(r["_name"]):
            continue
        if (r.get("has_website") or "").strip().lower() not in ("no", "", "yes - dead", "yes - social"):
            continue
        cat = (r.get("category") or "").strip().lower()
        if window == "lunch":
            if cat in FOOD or cat not in LUNCH_OK:
                continue
        if city_filter and city_filter.lower() not in (r.get("city") or "").lower():
            continue
        try:
            if int(float(r.get("review_count") or 0)) < MIN_REVIEWS:
                continue
            if float(r.get("rating") or 0) < MIN_RATING:
                continue
        except ValueError:
            continue
        scored.append((score(r, city_filter), r))

    scored.sort(key=lambda x: -x[0])
    for sc, r in scored:
        nm = r["_name"].lower()
        if nm in used_names:
            continue
        used_names.add(nm)
        r["_score"] = sc
        picks.append(r)
        if len(picks) >= count:
            break
    return picks


OPENERS = {
    "auto repair": "I noticed {name} has {reviews} reviews and no website — when people search for a mechanic near {area}, your competitors show up and you don't.",
    "hair salon": "{name} has {reviews} reviews and no website — new clients searching for a salon in {area} are finding everyone but you.",
    "nail salon": "{name} has {reviews} reviews and no website — people searching for nails in {area} can't find you, only your competitors.",
    "barbershop": "{name} has {reviews} reviews and nothing online — guys searching for a barber in {area} aren't finding you.",
    "cleaning service": "{name} has {reviews} reviews and no website — cleaning is a business people search for and check before they call.",
    "landscaping": "{name} has {reviews} reviews and no website — homeowners in {area} are searching for landscapers and getting your competitors.",
}
DEFAULT_OPENER = "I noticed {name} has {reviews} reviews and no website — people searching for {cat} in {area} are finding your competitors instead."


def opener_for(row: dict) -> str:
    cat = (row.get("category") or "business").lower()
    area = (row.get("city") or "your area").split(",")[0].strip() or "your area"
    reviews = row.get("review_count") or "great"
    tpl = OPENERS.get(cat, DEFAULT_OPENER)
    return tpl.format(name=row["_name"], reviews=reviews, area=area, cat=cat)


def pitch_note(row: dict) -> str:
    """What they have instead of a site — say this, not a generic 'no website'."""
    v = row.get("_verified") or {}
    return (v.get("pitch_note") or "").strip()


def build_mockups(picks: list, quiet: bool = False) -> None:
    try:
        import mockup_uploader
    except Exception as e:
        print(f"  ! mockup_uploader unavailable ({e}) — skipping previews")
        return
    for i, r in enumerate(picks, 1):
        if not quiet:
            print(f"  [{i}/{len(picks)}] building preview for {r['_name']} ...")
        try:
            r["_preview"] = mockup_uploader.upload_mockup(
                name=r["_name"],
                category=r.get("category") or "local business",
                phone=pretty_phone(r["_phone"]),
                city=r.get("city") or "Philadelphia, PA",
                address=r.get("address") or "",
                website=r.get("website") or "",
            ) or ""
        except Exception as e:
            print(f"      ! preview failed: {e}")
            r["_preview"] = ""


SHEET_CSS = """
:root{color-scheme:light dark;--fg:#111;--mut:#666;--line:#ddd;--acc:#0b6;}
@media(prefers-color-scheme:dark){:root{--fg:#eee;--mut:#999;--line:#333;}}
*{box-sizing:border-box}
body{font:16px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;margin:0;padding:20px;color:var(--fg);max-width:820px;margin-inline:auto}
h1{font-size:22px;margin:0 0 4px}
.sub{color:var(--mut);font-size:14px;margin-bottom:20px}
.card{border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-bottom:14px}
.top{display:flex;justify-content:space-between;gap:10px;align-items:baseline;flex-wrap:wrap}
.n{font-weight:700;font-size:18px}
.meta{color:var(--mut);font-size:13px}
a.tel{display:inline-block;font-size:20px;font-weight:700;color:var(--acc);text-decoration:none;margin:8px 0}
.say{background:rgba(128,128,128,.10);border-left:3px solid var(--acc);padding:8px 12px;border-radius:6px;margin:8px 0;font-size:15px}
.links a{font-size:14px;margin-right:14px}
.out{margin-top:8px;font-size:13px;color:var(--mut)}
.script{border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:22px 0;font-size:15px}
.script h2{font-size:16px;margin:0 0 8px}
.script li{margin-bottom:6px}
"""


def write_sheet(picks: list, date: str, window: str, emailed: dict) -> tuple:
    SHEET_DIR.mkdir(exist_ok=True)
    md_path = SHEET_DIR / f"{date}.md"
    html_path = SHEET_DIR / f"{date}.html"
    csv_path = SHEET_DIR / f"{date}.csv"

    md = [f"# Call sheet — {date}", "",
          f"{len(picks)} businesses · no website · {PRICE} + {MONTHLY} · window: {window}", ""]
    cards = []
    for i, r in enumerate(picks, 1):
        nm, ph = r["_name"], pretty_phone(r["_phone"])
        cat = r.get("category") or ""
        city = (r.get("city") or "").split("(")[0].strip()
        rev, rat = r.get("review_count") or "?", r.get("rating") or "?"
        prev = r.get("_preview") or ""
        was = emailed.get(nm.lower())
        say = opener_for(r)
        note = pitch_note(r)

        md += [f"## {i}. {nm}", f"- **{ph}** · {cat} · {city}",
               f"- {rat}★ / {rev} reviews · no website"
               + (f" · emailed {was}" if was else ""),
               *([f"- What they have instead: {note}"] if note else []),
               f"- Preview: {prev or '(none)'}",
               f"- Open with: _{say}_", "- Outcome: ", ""]

        cards.append(f"""<div class="card">
<div class="top"><span class="n">{i}. {html.escape(nm)}</span>
<span class="meta">{html.escape(cat)} · {html.escape(city)}</span></div>
<div class="meta">{rat}★ · {rev} reviews · no website{' · emailed ' + was if was else ''}</div>
<a class="tel" href="tel:+1{r['_phone']}">{ph}</a>
<div class="say">{html.escape(say)}</div>
{f'<div class="meta"><b>Instead of a site they have:</b> {html.escape(note)}</div>' if note else ''}
<div class="links">{f'<a href="{prev}" target="_blank">▶ Their preview site</a>' if prev else '<span class="meta">no preview built</span>'}
{f'<a href="https://www.google.com/maps/search/{html.escape(nm)}" target="_blank">Maps</a>' if nm else ''}</div>
<div class="out">Outcome: ______________________________</div>
</div>""")

    script_html = f"""<div class="script"><h2>The 60-second pitch</h2><ol>
<li><b>Name + why:</b> "Hi, is the owner around? My name's Maya, I build websites for small businesses here in Philly."</li>
<li><b>The hook (per lead above):</b> lead with their reviews and the fact that they're invisible in search.</li>
<li><b>The proof:</b> "I already built you one — I can text you the link right now, takes ten seconds to look."<br>
<i>Send the preview link while they're on the phone. That's the whole close.</i></li>
<li><b>The price:</b> "{PRICE} one time — domain, hosting, SSL and setup included, live in 7 days. After that it's {MONTHLY} to keep it hosted and updated. No contract."</li>
<li><b>The ask:</b> "Want me to put your real hours and photos on it and send it back tomorrow?"</li>
</ol>
<b>Objections:</b> <i>"I have Facebook"</i> → "That's good — this is what shows up on Google, where people search."&nbsp;
<i>"Too expensive"</i> → "One new customer a month covers it."&nbsp;
<i>"Send me info"</i> → "Already did — check your texts, I'll follow up Thursday."&nbsp;
<i>"Not interested"</i> → thank them, hang up, next call.
</div>"""

    html_doc = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Call sheet {date}</title><style>{SHEET_CSS}</style></head><body>
<h1>Call sheet — {date}</h1>
<div class="sub">{len(picks)} businesses · no website · tap a number to dial · {PRICE} + {MONTHLY}</div>
{script_html}
{''.join(cards)}
</body></html>"""

    md_path.write_text("\n".join(md))
    html_path.write_text(html_doc)

    with open(csv_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "name", "phone", "category", "city", "rating",
                    "reviews", "preview_url", "previously_emailed", "outcome", "notes"])
        for r in picks:
            w.writerow([date, r["_name"], pretty_phone(r["_phone"]),
                        r.get("category", ""), r.get("city", ""), r.get("rating", ""),
                        r.get("review_count", ""), r.get("_preview", ""),
                        emailed.get(r["_name"].lower(), ""), "", ""])
    return md_path, html_path, csv_path


def print_outcomes() -> None:
    tally = Counter()
    for path in sorted(glob.glob(str(SHEET_DIR / "*.csv"))):
        for row in csv.DictReader(open(path)):
            out = (row.get("outcome") or "").strip().lower() or "(not logged)"
            tally[out] += 1
    total = sum(tally.values())
    print(f"\n  Calls queued: {total}")
    for k, v in tally.most_common():
        print(f"    {v:>4}  {k}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD (default: tomorrow)")
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--window", choices=["lunch", "any"], default="lunch")
    ap.add_argument("--city", default="Philadelphia")
    ap.add_argument("--no-mockups", action="store_true")
    ap.add_argument("--verified-only", action="store_true",
                    help="only leads confirmed by hand in verified_sites.csv")
    ap.add_argument("--dry-run", action="store_true", help="don't record picks in state")
    ap.add_argument("--outcomes", action="store_true", help="print outcome tally and exit")
    ap.add_argument("--rebuild", action="store_true",
                    help="regenerate the sheet from an existing day's CSV (no new leads)")
    args = ap.parse_args()

    if args.outcomes:
        print_outcomes()
        return

    date = args.date or (dt.date.today() + dt.timedelta(days=1)).isoformat()

    if args.rebuild:
        src = SHEET_DIR / f"{date}.csv"
        if not src.exists():
            print(f"  No sheet for {date}.")
            return
        verified = load_verified()
        picks = []
        for row in csv.DictReader(open(src)):
            phone = norm_phone(row["phone"])
            picks.append({"_name": row["name"], "_phone": phone,
                          "_preview": row.get("preview_url", ""),
                          "_verified": verified.get(phone),
                          "category": row.get("category", ""), "city": row.get("city", ""),
                          "rating": row.get("rating", ""), "review_count": row.get("reviews", "")})
        md, htm, _ = write_sheet(picks, date, args.window, load_emailed_names())
        print(f"  Rebuilt {htm}")
        return
    state = load_state()

    print(f"\n  Building call sheet for {date} ({args.window} window, {args.city}) ...")
    picks = pick(args.count, args.window, args.city, state, args.verified_only)
    if not picks:
        print("  No leads matched. Try --window any or a different --city.")
        return
    print(f"  {len(picks)} leads selected.")

    if not args.no_mockups:
        build_mockups(picks)

    emailed = load_emailed_names()
    md, htm, csvp = write_sheet(picks, date, args.window, emailed)

    if not args.dry_run:
        for r in picks:
            state["queued"][r["_phone"]] = {"name": r["_name"], "date": date}
        save_state(state)

    print(f"\n  Call sheet : {htm}")
    print(f"  Markdown   : {md}")
    print(f"  Log CSV    : {csvp}\n")
    for i, r in enumerate(picks, 1):
        print(f"  {i:>2}. {r['_name'][:34]:34} {pretty_phone(r['_phone'])}  "
              f"{(r.get('rating') or '?')}★/{r.get('review_count') or '?'}  "
              f"{'preview ✓' if r.get('_preview') else 'preview —'}")
    print()


if __name__ == "__main__":
    main()

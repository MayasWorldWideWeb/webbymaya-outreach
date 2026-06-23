#!/usr/bin/env python3
"""
fb_posts.py — Generate monthly Facebook group post drafts for WebByMaya.

Outputs 4 posts per month, rotated across different angles so they don't
feel repetitive week-to-week. Posts target Philly small-business FB groups.

Best groups to post in:
  - Philadelphia Small Business Network
  - Philly Black Business Alliance
  - Support Philly Small Businesses
  - Philadelphia Business Owners
  - North/South/West Philly neighborhood groups

USAGE
    python3 fb_posts.py                          # current month
    python3 fb_posts.py --month 7 --year 2026
    python3 fb_posts.py --out fb_july.txt        # save to file
"""

import argparse
import datetime
import textwrap
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

# 12 monthly angle rotations × 4 posts each = 48 unique posts before repeating
# Each tuple: (title/angle, body_template, cta_style)
ANGLES = [
    # Week 1: Social proof / results angle
    {
        "title": "A local business just went from invisible to page 1 of Google",
        "body": """\
I've been building free website previews for Philly businesses this month, and one \
of the things I hear most is: "I didn't realize how many customers I was losing."

If your business doesn't have a website (or your current one looks bad on phones), \
people searching Google right now literally cannot find you.

I build clean, mobile-ready sites for local Philly businesses. No monthly fees. \
Most sites go live in about a week.

Free preview for any business in this group — I'll build it before you commit to \
anything. 👇""",
        "cta": "webbymaya.com/book — takes 2 minutes to fill out",
    },
    # Week 2: Direct offer angle
    {
        "title": "Free website mockup for any Philly business (no commitment)",
        "body": """\
Hey Philly business owners 👋

I'm a local web designer and I want to build your business a free website mockup — \
no strings attached.

Here's how it works:
→ Fill out my short form (2 minutes)
→ I build a preview of your site in 48 hours
→ If you love it, we go live for $799
→ If not, no hard feelings — keep the preview

I've been doing this for businesses across Philly and South Jersey. Most owners are \
shocked that a professional site is this affordable.

Drop a comment or use the link below if you're interested. 👇""",
        "cta": "webbymaya.com/book",
    },
    # Week 3: Problem/pain angle
    {
        "title": "If your business isn't on Google, you're losing customers every day",
        "body": """\
Quick question for Philly business owners:

When someone searches for your type of business in your neighborhood right now — \
does your name come up?

If you don't have a website, the answer is no. And that means someone else is \
getting that customer instead of you.

I build websites specifically for local Philly businesses. starting at $499, no monthly fees, \
live in about a week.

I also do a free mockup first — you see the whole site before paying anything.

Reply or comment if you want me to build a free preview for your business. 💪""",
        "cta": "webbymaya.com/book",
    },
    # Week 4: Value/differentiator angle
    {
        "title": "What $799 gets you (Philly web designer, no monthly fees)",
        "body": """\
A lot of business owners think a professional website costs $3,000+/year with \
ongoing monthly fees. I want to clear that up.

Here's what my Standard package includes for $799:
✓ 5-page website (Home, About, Services, Gallery, Contact)
✓ Mobile-optimized — looks great on every phone
✓ Google Analytics so you can see your traffic
✓ SSL certificate (the padlock in the browser)
✓ 1 year of hosting included
✓ Live in about a week
✓ No monthly fees — ever

I also do a free mockup before you commit to anything.

DM me or use the link below if you want to see what your business site could look like. 👇""",
        "cta": "webbymaya.com/book — free mockup, no commitment",
    },
]


def get_posts(month: int, year: int) -> list[dict]:
    """Return 4 post drafts for the given month."""
    # Rotate which angle is week 1 based on the month number
    posts = []
    for week in range(1, 5):
        angle_idx = (month - 1 + week - 1) % len(ANGLES)
        angle = ANGLES[angle_idx]

        # Week-specific date hint (approximate posting day)
        week_start = datetime.date(year, month, 1) + datetime.timedelta(weeks=week - 1)
        post_date  = week_start + datetime.timedelta(days=1)  # post on Tuesdays
        if post_date.month != month:
            post_date = datetime.date(year, month, 28)

        posts.append({
            "week":      week,
            "post_date": post_date.strftime("%B %d"),
            "title":     angle["title"],
            "body":      angle["body"],
            "cta":       angle["cta"],
        })
    return posts


def format_posts(posts: list[dict], month_name: str) -> str:
    lines = [f"{'='*60}", f"  WebByMaya FB Post Drafts — {month_name}", f"{'='*60}", ""]
    lines.append("BEST GROUPS TO POST IN:")
    lines.append("  - Philadelphia Small Business Network")
    lines.append("  - Support Philly Small Businesses")
    lines.append("  - Philadelphia Business Owners")
    lines.append("  - Philly Black Business Alliance")
    lines.append("  - Your neighborhood group (Fishtown, Kensington, etc.)")
    lines.append("")
    lines.append("TIP: Space posts 5-7 days apart. Don't post the same thing twice.")
    lines.append("")

    for post in posts:
        lines.append(f"{'─'*60}")
        lines.append(f"  WEEK {post['week']}  —  Post around {post['post_date']}")
        lines.append(f"{'─'*60}")
        lines.append("")
        lines.append(f"TITLE / FIRST LINE:")
        lines.append(f"  {post['title']}")
        lines.append("")
        lines.append("BODY:")
        for para in post["body"].split("\n"):
            if para.strip():
                lines.append(f"  {para}")
            else:
                lines.append("")
        lines.append("")
        lines.append(f"LINK / CTA:")
        lines.append(f"  {post['cta']}")
        lines.append("")

    lines.append(f"{'='*60}")
    lines.append("Generated by fb_posts.py — WebByMaya outreach toolkit")
    lines.append(f"{'='*60}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", type=int, default=datetime.date.today().month)
    ap.add_argument("--year",  type=int, default=datetime.date.today().year)
    ap.add_argument("--out",   default="", help="Save to file instead of printing")
    args = ap.parse_args()

    month_name = datetime.date(args.year, args.month, 1).strftime("%B %Y")
    posts      = get_posts(args.month, args.year)
    output     = format_posts(posts, month_name)

    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
        print(f"Saved: {args.out}")
    else:
        print(output)

    # Also save to a dated file in the scripts dir automatically
    auto_path = SCRIPT_DIR / f"fb_posts_{args.year}_{args.month:02d}.txt"
    auto_path.write_text(output, encoding="utf-8")
    if not args.out:
        print(f"\n(Also saved to {auto_path.name})")


if __name__ == "__main__":
    main()

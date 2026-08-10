"""
offer.py — SINGLE SOURCE OF TRUTH for WebByMaya's offer copy.

Every customer-facing surface (mockup site, cold emails, reply emails,
follow-ups, proposals, Craigslist, etc.) MUST pull its price + what's-included
language from here so the pitch is identical everywhere. If the offer changes,
change it in ONE place: this file.

Canonical offer (decided 2026-07):
  • $499 one-page  /  $799 five-page
  • INCLUDES a FREE domain + 1 YEAR of hosting, SSL, setup, 30-day support
  • After the first free year, hosting + maintenance is just $29/mo
  • Payment plan available: $150 now, $349 on launch
"""

# Physical postal address shown in every email footer (CAN-SPAM requirement).
BUSINESS_ADDRESS = "7213 Montour St, Philadelphia, PA 19111"

PRICE          = "$499"        # 1-page starter (headline price)
PRICE_5PAGE    = "$799"        # 5-page
PLAN           = "$150 now, $349 on launch"
MONTHLY        = "$29/mo"      # hosting + maintenance, starts AFTER the free year

# Live Stripe $499 Payment Link (created 2026-07 via jarvis/.env.local key).
# Product: "WebByMaya Website — Starter". Price id: price_1TxulwAJ84QZjwZkOCGqwMYl
CHECKOUT_URL   = "https://buy.stripe.com/8x23cudmW2J97r28pB1ck02"
BOOKING_URL    = "https://webbymaya.com/book"

# What EVERY sale includes — this list must appear (in some form) in every pitch.
INCLUDES = [
    "Free domain — first year on us",
    "Free website hosting — first year on us",
    "SSL security certificate (https)",
    "Full setup — nothing technical on your end",
    "30-day support after launch",
]

# Tight one-liners for space-constrained spots (email sign-offs, badges).
OFFER_ONELINE = (f"{PRICE} — includes a free domain + 1 year of hosting, SSL & full setup, "
                 f"live in 7 days. After year one, hosting & maintenance is just {MONTHLY}.")

# The recurring line, stated consistently wherever monthly is mentioned.
MONTHLY_LINE   = f"Free domain + 1 year of hosting included. After that, just {MONTHLY} to keep it live & maintained."


def includes_text() -> str:
    """Plain-text bullet list for text emails / SMS."""
    return "\n".join(f"  ✓ {item}" for item in INCLUDES)


def includes_html(accent: str = "#C9A96E") -> str:
    """HTML bullet list for rich emails / the mockup page."""
    rows = "".join(
        f'<div style="margin:4px 0;color:#555">'
        f'<span style="color:{accent};font-weight:700">&#10003;</span>&nbsp; {item}</div>'
        for item in INCLUDES
    )
    return rows

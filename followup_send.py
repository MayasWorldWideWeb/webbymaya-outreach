#!/usr/bin/env python3
"""
followup_send.py — WebByMaya Automated Follow-Up Sequences
Reads send logs, finds prospects who haven't replied, sends follow-ups.

Sequence:
  Day 3  → Follow-up 1: "Did you see the preview?"
  Day 7  → Follow-up 2: Social proof / different angle
  Day 14 → Follow-up 3: Closing the file (urgency close)

Usage:
  python3 followup_send.py               # send up to 75 follow-ups
  python3 followup_send.py --limit 50    # custom limit
  python3 followup_send.py --dry-run     # preview without sending
"""
import argparse, csv, datetime, json, os, re as _re, sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from batch_send_outreach import send_email, normalize_category, SKIP_DOMAINS, html_card, _ep, _ecta, SUPPRESSED_EMAILS, clean_business_name
from sb import log_email
from collections import defaultdict

GITHUB_PAGES_BASE = "https://mayasworldwideweb.github.io/previews"

def _mockup_slug(name: str) -> str:
    return _re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

def _resolve_mockup_url(mockup_url: str, name: str) -> str:
    """Return stored mockup URL, or reconstruct GitHub Pages URL using token slug."""
    from mockup_uploader import _token_slug
    if mockup_url and mockup_url.startswith("http"):
        if "supabase.co" in mockup_url:
            return f"{GITHUB_PAGES_BASE}/{_token_slug(name)}.html"
        return mockup_url
    return f"{GITHUB_PAGES_BASE}/{_token_slug(name)}.html"

# Additional domains to skip in follow-ups (government, courts, arbitration, etc.)
_SKIP_FOLLOWUP_DOMAINS = SKIP_DOMAINS | {
    "phila.gov", "courts.phila.gov", "pa.gov", "nj.gov", "state.pa.us",
    "adr.org", "zipappointments.com", "aspwv.com", "motomundohn.com",
    "courts.state.pa.us", "usps.com", "gmail.com",  # gmail = personal, not biz
}

_SKIP_EMAIL_PREFIXES = {
    "jury", "rebuild", "noreply", "no-reply", "donotreply",
    "customerservice", "customer.service", "postmaster", "abuse",
    "reservations", "careers", "jobs", "hr", "legal",
    "collegeandcareer", "accessibility", "webmaster",
    "privacy", "compliance", "billing", "accounting",
    "marketing", "press", "media", "server",
}

# Domain fragments that signal government, schools, civic orgs, or unrelated industries
_SKIP_DOMAIN_FRAGMENTS = {
    "senate", "pasenate", "house.gov", "court", "phila.gov", "philasd",
    "illinois1call", "811", "redlionpa", "lora-alliance",
    "school", "district", "university", "college", "edu",
}

_US_TLDS = {
    "com", "net", "org", "io", "co", "us", "biz", "info",
    "edu", "gov", "mil", "app", "studio", "shop", "store",
}

def _is_junk_email(email: str, business_name: str = "") -> bool:
    if not email or "@" not in email:
        return True
    local, domain = email.lower().rsplit("@", 1)
    tld = domain.rsplit(".", 1)[-1]

    # Drop foreign TLDs — we target US businesses
    if tld not in _US_TLDS:
        return True

    # Drop all .gov emails — government orgs are never our clients
    if tld == "gov":
        return True

    if domain in _SKIP_FOLLOWUP_DOMAINS:
        return True
    if any(frag in domain for frag in _SKIP_DOMAIN_FRAGMENTS):
        return True
    if any(local.startswith(p) for p in _SKIP_EMAIL_PREFIXES):
        return True
    # "firstname.lastname@domain" pattern usually signals wrong org contact
    if _re.match(r'^[a-z]+\.[a-z]+$', local) and tld == "org":
        return True

    # Domain mismatch check — domain should share at least one meaningful word
    # with the business name, OR be a recognized generic provider
    _GENERIC_PROVIDERS = {"gmail", "yahoo", "hotmail", "outlook", "aol",
                          "icloud", "me", "mac", "protonmail", "live"}
    domain_base = domain.split(".")[0]
    if domain_base not in _GENERIC_PROVIDERS and business_name:
        # Use all words 3+ chars — if none appear in the domain, it's a mismatch
        biz_words = set(_re.findall(r'[a-z]{3,}', business_name.lower()))
        if biz_words and not any(w in domain_base for w in biz_words):
            return True  # domain has zero overlap with business name

    return False

_GENERIC_OPENERS = {
    "the","a","an","for","by","at","of","my","in","on","up","to",
    "new","old","your","our","its","and","or",
}

def _first_name(business_name: str) -> str:
    """Extract a usable greeting name from a business name."""
    name  = business_name.strip()
    parts = name.split()
    first = parts[0] if parts else name
    # Remove trailing punctuation / apostrophe artifacts
    first = _re.sub(r"[‘’]s?$", "", first, flags=_re.IGNORECASE).strip()
    # All-caps acronym → use full name
    if first.isupper() and len(first) <= 5:
        return name
    # Generic openers or very short words → use full name
    if first.lower() in _GENERIC_OPENERS or len(first) <= 2:
        return name
    # Use capitalize() to avoid "Joe'S" from title()
    return first[0].upper() + first[1:] if first else first

FOLLOWUP_LOG = SCRIPT_DIR / f"followup_log_{datetime.date.today()}.csv"
FOLLOWUP_STATE = Path.home() / ".webbymaaya/followup_state.json"

# Which days trigger which follow-up number.
# First 3 touches are fast (day 3 / 7 / 14); after that we check in ~monthly,
# indefinitely, until the prospect replies "no" or the address bounces (both of
# which land them on the shared suppression list, bounce_log.csv).
SEQUENCE = {3: 1, 7: 2, 14: 3}
MONTHLY_INTERVAL = 30            # days between check-ins after touch #3

def _trigger_day(num: int) -> int:
    """Day (since first contact) when follow-up `num` becomes due. Unbounded."""
    fast = {1: 3, 2: 7, 3: 14}
    if num in fast:
        return fast[num]
    return 14 + (num - 3) * MONTHLY_INTERVAL   # 44, 74, 104, ...

LOG_FIELDS = ["timestamp","name","category","email","followup_num","subject","status","notes"]

# ── Subject lines ────────────────────────────────────────────────────────────

def _subject(name: str, category: str, num: int) -> str:
    first = _first_name(name)
    cat   = (category or "").lower()
    if num == 1:
        return f"Did you get a chance to look, {first}?"
    if num == 2:
        lines = {
            "nail salon":        f"Other nail salons in Philly are booking online now",
            "hair salon":        f"Clients are searching online — is {name} showing up?",
            "barbershop":        f"Quick question about {name}",
            "restaurant":        f"Your competitors are getting found on Google — {name}?",
            "cafe":              f"Is {name} showing up when people search nearby?",
            "bakery":            f"Customers are searching — can they find {name}?",
            "auto repair":       f"One thing most auto shops are missing (quick look)",
            "cleaning service":  f"New cleaning clients search online first — are you there?",
            "spa":               f"Spa clients search Google before they call — is {name} ready?",
            "massage":           f"Quick follow-up on {name}'s website preview",
            "florist":           f"Did you see what I built for {name}?",
            "photographer":      f"Photographers with websites book 3x more clients",
            "gym":               f"Fitness clients search online — is {name} visible?",
        }
        return lines.get(cat, f"Quick follow-up — {name}'s website preview")
    if num == 3:
        return f"Closing {name}'s file on Friday — last chance"
    # num >= 4 — gentle recurring check-in, rotated so it's never identical twice
    checkins = [
        f"Still here whenever you're ready, {first}",
        f"Quick check-in on {name}'s website",
        f"Reviving {name}'s free preview",
        f"Anytime you want to get {name} online",
        f"{name} — the free preview's still yours",
    ]
    return checkins[(num - 4) % len(checkins)]


# ── Email bodies ─────────────────────────────────────────────────────────────

def _body(name: str, category: str, mockup_url: str, phone: str, num: int, email: str = "") -> tuple:
    """Returns (plain_text, html)"""
    first    = _first_name(name)
    cat      = (category or "business").lower()
    cta_url  = mockup_url or "https://webbymaya.com"

    if num == 1:
        plain = f"""Hey {first},

Just wanted to make sure this didn't get lost — I put together a free website preview for {name} a few days ago.

Takes 30 seconds to look at: {cta_url}

No commitment, no catch. If you like what you see, we can have it live in 7 days starting at $499 — free domain + 1 year of hosting included ($29/mo after year one).

If the timing's off, no worries — just let me know.

— Maya
WebByMaya.com"""

        html = html_card(
            _ep(f"Hey {first},")
            + _ep(f"Just wanted to make sure this didn't get lost — I put together a <strong>free website preview</strong> for {name} a few days ago.")
            + _ecta(cta_url, "&#128064;&nbsp;&nbsp;See Your Free Preview &rarr;")
            + _ep("No commitment, no catch. If you like what you see, we can have it <strong>live in 7 days starting at $499</strong> — free domain + 1 year of hosting included ($29/mo after year one).")
            + _ep("If the timing's off, no worries — just reply and let me know."),
            email=email,
        )

    elif num == 2:
        hooks = {
            "nail salon":    (f"Most nail salons in Philly still don't have a real website — which means when someone searches \"{cat} near me,\" they're finding your competitors instead of {name}.",
                              "Every day without a site is a booking you're not getting."),
            "barbershop":    (f"New clients in your area are searching for barbershops right now. Without a website, {name} is invisible to them.",
                              "A site that runs 24/7 is the best hire you'll make this year."),
            "restaurant":    (f"Restaurants with websites get 3x more foot traffic from Google searches. {name} is missing those customers every single day.",
                              "Your food deserves to be found."),
            "hair salon":    (f"When someone moves to your area and searches for a hair salon, is {name} showing up? Right now, probably not.",
                              "Let's fix that."),
            "auto repair":   (f"People search for auto shops before they break down, not after. {name} needs to be there when they're looking.",
                              "Your preview is ready — took me about an hour to build."),
            "cleaning service": (f"Homeowners search Google before they call anyone. Without a website, {name} isn't even in the conversation.",
                                 "I'd love to change that for you."),
        }
        hook, closer = hooks.get(cat, (
            f"Businesses without websites are invisible to the 80% of customers who search online first. I built {name} a preview so you could see exactly what's possible.",
            "Takes 30 seconds to look at."
        ))

        plain = f"""Hey {first},

{hook}

{closer}

Your preview is still live here: {cta_url}

Starting at $499. Live in 7 days. Free domain + 1 year of hosting included ($29/mo after year one).

— Maya
WebByMaya.com"""

        html = html_card(
            _ep(f"Hey {first},")
            + _ep(hook)
            + _ep(closer)
            + _ecta(cta_url, f"View {name}&#39;s Preview &rarr;")
            + _ep("<strong>Starting at $499. Live in 7 days. Free domain + 1 year of hosting included</strong> ($29/mo after year one)."),
            email=email,
        )

    elif num == 3:
        plain = f"""Hey {first},

I've reached out a couple of times about a free website preview I built for {name}, but haven't heard back — so I'm going to close out your file on Friday to make room for new clients.

If you want to take one last look before I do: {cta_url}

If the timing just isn't right, no hard feelings at all. I'll be here when you're ready.

— Maya
WebByMaya.com"""

        html = html_card(
            _ep(f"Hey {first},")
            + _ep(f"I've reached out a couple of times about a free website preview I built for <strong>{name}</strong>, but haven't heard back — so I'm going to <strong>close out your file on Friday</strong> to make room for new clients.")
            + _ep("If you want to take one last look before I do:")
            + _ecta(cta_url, "Take One Last Look &rarr;")
            + _ep("If the timing just isn't right, no hard feelings at all. I'll be here when you're ready."),
            email=email,
        )

    else:  # num >= 4 — recurring monthly check-in, low-key, easy opt-out
        plain = f"""Hey {first},

Just checking back in — I'd still love to get {name} online whenever the timing's right. The free preview I built is here if you'd like a look: {cta_url}

Starting at $499, live in 7 days — free domain + 1 year of hosting included ($29/mo after year one). No rush at all.

If you'd rather I stop checking in, just reply "stop" and I won't email again.

— Maya
WebByMaya.com"""

        html = html_card(
            _ep(f"Hey {first},")
            + _ep(f"Just checking back in — I'd still love to get <strong>{name}</strong> online whenever the timing's right. The free preview I built is here if you'd like a look:")
            + _ecta(cta_url, "See Your Free Preview &rarr;")
            + _ep("Starting at $499, live in 7 days — free domain + 1 year of hosting included ($29/mo after year one). No rush at all.")
            + _ep("If you&#39;d rather I stop checking in, just reply &ldquo;stop&rdquo; and I won&#39;t email again."),
            email=email,
        )

    return plain, html


# ── State tracking ────────────────────────────────────────────────────────────

def _load_state() -> dict:
    """Returns {email: {"fu1": date, "fu2": date, "fu3": date, "unsubscribed": bool}}"""
    try:
        return json.loads(FOLLOWUP_STATE.read_text())
    except Exception:
        return {}

def _save_state(state: dict):
    FOLLOWUP_STATE.parent.mkdir(parents=True, exist_ok=True)
    FOLLOWUP_STATE.write_text(json.dumps(state, indent=2))

def _mark_sent(state: dict, email: str, num: int):
    if email not in state:
        state[email] = {}
    state[email][f"fu{num}"] = str(datetime.date.today())


# ── Load all sent emails from logs ───────────────────────────────────────────

def _load_sent_history() -> list:
    """Returns list of dicts: {name, category, email, sent_date, mockup_url}"""
    records = []
    seen    = {}  # email → first-send record (we only follow up on first contact)

    for log_file in sorted(SCRIPT_DIR.glob("send_log_*.csv")):
        with open(log_file, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("status","") != "sent":
                    continue
                email = (row.get("email_sent_to","") or "").strip().lower()
                if not email or "@" not in email:
                    continue
                if email in seen:
                    continue  # already have first contact
                try:
                    ts = datetime.datetime.fromisoformat(row["timestamp"]).date()
                except Exception:
                    continue
                notes_val = row.get("notes","")
                mockup_val = row.get("mockup_url","") or (notes_val if notes_val.startswith("http") else "")
                seen[email] = {
                    "name":       clean_business_name(row.get("name","")),
                    "category":   row.get("category",""),
                    "email":      email,
                    "sent_date":  ts,
                    "mockup_url": mockup_val,
                }

    # Also check seasonal logs for mockup URLs
    for log_file in sorted(SCRIPT_DIR.glob("seasonal_log_*.csv")):
        with open(log_file, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("status","") not in ("sent","dry_run"):
                    continue
                email = (row.get("email","") or "").strip().lower()
                if email in seen and not seen[email].get("mockup_url"):
                    seen[email]["mockup_url"] = row.get("mockup_url","")

    return list(seen.values())


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit",   type=int, default=250)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    today    = datetime.date.today()
    state    = _load_state()
    history  = _load_sent_history()
    log_rows = []

    sent_today = 0
    skipped    = 0
    counts     = defaultdict(int)

    print(f"\n{'='*58}")
    print(f"  WebByMaya Follow-Up Engine  {'[DRY RUN] ' if args.dry_run else ''}— {today}")
    print(f"  {len(history)} unique contacts in history")
    print(f"{'='*58}\n")

    for record in history:
        if sent_today >= args.limit:
            break

        email      = record["email"]
        name       = record["name"]
        category   = normalize_category(name, record["category"])
        sent_date  = record["sent_date"]
        mockup_url = record["mockup_url"] or ""
        days_since = (today - sent_date).days
        es         = state.get(email, {})

        # Skip junk / platform emails
        if _is_junk_email(email, business_name=name):
            skipped += 1
            continue

        # Skip if opted out (local flag) OR on the shared suppression list —
        # bounce_log.csv holds both hard bounces (sync_bounces.py) and
        # "not interested / stop" replies (auto_reply.py). This is the gate that
        # makes an unbounded cadence safe: we only stop on no / bad-address.
        if es.get("unsubscribed") or email in SUPPRESSED_EMAILS:
            skipped += 1
            continue

        # Determine the next pending follow-up — unbounded monthly cadence.
        # Find the lowest follow-up number not yet sent; send it if it's due.
        fu_num = None
        n = 1
        while n <= 200:                      # safety ceiling (~16 yrs of monthlies)
            if not es.get(f"fu{n}"):
                if days_since >= _trigger_day(n):
                    fu_num = n
                break                         # lowest unsent touch decides
            n += 1

        if fu_num is None:
            skipped += 1
            continue

        mockup_url = _resolve_mockup_url(record.get("mockup_url", ""), name)
        subject    = _subject(name, category, fu_num)
        plain, html = _body(name, category, mockup_url, "", fu_num, email=email)

        if args.dry_run:
            print(f"  [FU{fu_num}] {name} <{email}>  (day {days_since})")
            print(f"         Subject: {subject}")
            print(f"         Mockup : {mockup_url}")
            counts[fu_num] += 1
            sent_today += 1
            continue

        ok, provider = send_email(email, subject, plain, html)
        status = "sent" if ok else "failed"
        if ok:
            _mark_sent(state, email, fu_num)
            counts[fu_num] += 1
            sent_today += 1
            print(f"  ✓ [FU{fu_num}] {name} <{email}>  via {provider}")
            # Log to Supabase
            try:
                log_email(name=name, category=category, email=email,
                          subject=subject, status="sent",
                          notes=f"followup_{fu_num}", provider=provider)
            except Exception:
                pass
        else:
            print(f"  ✗ [FU{fu_num}] {name} <{email}> — send failed")

        log_rows.append({
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
            "name":      name, "category": category, "email": email,
            "followup_num": fu_num, "subject": subject,
            "status":    status, "notes": provider if ok else "failed",
        })

    # Save state
    if not args.dry_run:
        _save_state(state)
        if log_rows:
            write_header = not FOLLOWUP_LOG.exists()
            with open(FOLLOWUP_LOG, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
                if write_header:
                    w.writeheader()
                w.writerows(log_rows)

    print(f"\n{'='*58}")
    print(f"  Follow-up 1 (day 3) : {counts[1]}")
    print(f"  Follow-up 2 (day 7) : {counts[2]}")
    print(f"  Follow-up 3 (day 14): {counts[3]}")
    monthly = sum(v for k, v in counts.items() if k >= 4)
    print(f"  Monthly check-ins   : {monthly}")
    print(f"  Total sent          : {sum(counts.values())}")
    print(f"  Skipped             : {skipped}")
    if args.dry_run:
        print(f"\n  (Dry run — nothing was sent)")
    print(f"{'='*58}\n")


if __name__ == "__main__":
    main()

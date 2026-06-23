#!/usr/bin/env python3
"""
generate_intake_form.py — WebByMaya Personalized Intake Form Generator

After a business replies YES, this generates a custom HTML form page
that shows their mockup preview, asks what they'd like to change,
and lets them select add-ons with live price calculation.

Uploads to Supabase Storage → returns public URL.
"""
import re, os, sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

SUPABASE_URL     = os.environ.get("SUPABASE_URL", "https://ycsauzlqsjjbusugshpz.supabase.co")
ANON_KEY         = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inljc2F1emxxc2pqYnVzdWdzaHB6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk0NjMzMTQsImV4cCI6MjA5NTAzOTMxNH0._rjYuGZch-CA4sfm2rV3lvs_ixDcQfNFg90KWsbe1HI"
# Service role key — has storage write permission
SERVICE_KEY      = os.environ.get("SUPABASE_SERVICE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inljc2F1emxxc2pqYnVzdWdzaHB6Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3OTQ2MzMxNCwiZXhwIjoyMDk1MDM5MzE0fQ.0qJY5I3THWHxPVVM49D8Ov1pmH91gMYb5bIXOOKJy1c")
BUCKET           = "mockups"

BASE_PRICE = 799

# Add-ons: (id, label, description, price, monthly)
ADDONS = [
    ("booking",     "Online Booking Button",          "Links to your existing Calendly, Square, or booking app",        99,  False),
    ("menu",        "Menu / Services PDF Page",        "Formatted menu or services list with photos",                    79,  False),
    ("gallery",     "Extra Photo Gallery Page",        "Additional gallery with up to 20 photos",                        79,  False),
    ("blog",        "Blog / News Section",             "Post updates, promotions, and announcements",                   149,  False),
    ("form",        "Contact Form + Auto-Reply",       "Smart contact form that emails you and auto-replies the client",  79,  False),
    ("spanish",     "Spanish Language Version",        "Full site translated to Spanish (or other language)",            199,  False),
    ("logo",        "Logo Design",                     "3 original concepts, 2 rounds of revisions, final files",       349,  False),
    ("rush",        "Rush Delivery (3 Days)",           "Done in 3 days instead of 7",                                   199,  False),
    ("extra_page",  "Extra Page",                      "One additional page (Team, FAQ, Events, Hours, etc.)",            99,  False),
    ("ecommerce",   "Online Store",                    "Sell products or services directly on your site",               599,  False),
    ("seo",         "Local SEO Setup",                 "Google Business profile, local citations, keyword targeting",    199,  False),
    ("maintenance", "Monthly Maintenance Plan",         "Updates, edits, and backups every month",                        79,  True),
]

# Category-specific default add-on suggestions
CAT_SUGGESTED = {
    "restaurant":       {"menu", "booking", "seo"},
    "cafe":             {"menu", "seo", "gallery"},
    "bakery":           {"gallery", "form", "seo"},
    "nail salon":       {"booking", "gallery", "seo"},
    "hair salon":       {"booking", "gallery", "seo"},
    "barbershop":       {"booking", "gallery", "seo"},
    "spa":              {"booking", "gallery", "seo"},
    "massage":          {"booking", "form", "seo"},
    "auto repair":      {"form", "seo", "extra_page"},
    "cleaning service": {"form", "seo", "extra_page"},
    "tattoo parlor":    {"gallery", "booking", "seo"},
    "photographer":     {"gallery", "blog", "seo"},
    "florist":          {"gallery", "booking", "seo"},
    "gym":              {"booking", "blog", "seo"},
    "pet grooming":     {"booking", "gallery", "form"},
}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _mockup_url(name: str, stored_url: str = "") -> str:
    if stored_url and stored_url.startswith("http"):
        return stored_url
    slug = _slug(name)
    return f"https://ycsauzlqsjjbusugshpz.supabase.co/storage/v1/object/public/mockups/{slug}.html"


def generate_html(name: str, category: str, mockup_url: str = "") -> str:
    slug         = _slug(name)
    preview_url  = _mockup_url(name, mockup_url)
    cat          = (category or "").strip().lower()
    suggested    = CAT_SUGGESTED.get(cat, set())

    addons_html  = ""
    addons_js    = "const prices = {};\n"
    for aid, label, desc, price, monthly in ADDONS:
        checked  = 'checked' if aid in suggested else ''
        badge    = '<span style="background:#1a3a1a;color:#5cb85c;font-size:10px;padding:2px 7px;border-radius:10px;margin-left:6px">RECOMMENDED</span>' if aid in suggested else ''
        mo_label = '/mo' if monthly else ''
        addons_js += f'prices["{aid}"] = {price};\n'
        addons_html += f"""
        <label class="addon-row" for="addon-{aid}">
          <input type="checkbox" id="addon-{aid}" name="addon_{aid}" value="{price}" {checked} onchange="calcTotal()">
          <div class="addon-info">
            <div class="addon-name">{label}{badge}</div>
            <div class="addon-desc">{desc}</div>
          </div>
          <div class="addon-price">+${price}{mo_label}</div>
        </label>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Customize Your Website — {name}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:-apple-system,BlinkMacSystemFont,'Inter','Segoe UI',Arial,sans-serif;
        background:#0a0a0a;color:#f0f0f0;min-height:100vh}}
  .header{{background:#111;border-bottom:1px solid #222;padding:18px 24px;display:flex;align-items:center;gap:14px}}
  .logo{{font-size:20px;font-weight:900;color:#fff}}
  .logo span{{color:#C9A96E}}
  .header-sub{{font-size:13px;color:#666;margin-top:2px}}
  .container{{max-width:720px;margin:0 auto;padding:32px 20px 60px}}
  h1{{font-size:26px;font-weight:800;color:#fff;margin-bottom:6px}}
  .subtitle{{color:#888;font-size:15px;margin-bottom:32px}}
  .section{{background:#111;border:1px solid #222;border-radius:12px;padding:28px;margin-bottom:20px}}
  .section-title{{font-size:14px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;
                  color:#C9A96E;margin-bottom:18px}}
  .preview-frame{{width:100%;height:340px;border:none;border-radius:8px;background:#0d0d0d}}
  .preview-link{{display:block;text-align:center;margin-top:10px;font-size:13px;color:#C9A96E;
                 text-decoration:none}}
  .stars{{display:flex;gap:8px;margin-bottom:16px}}
  .star{{font-size:32px;cursor:pointer;color:#333;transition:color .15s}}
  .star.active{{color:#C9A96E}}
  textarea{{width:100%;background:#0d0d0d;border:1px solid #2a2a2a;border-radius:8px;
             padding:14px;color:#f0f0f0;font-size:14px;line-height:1.7;resize:vertical;
             font-family:inherit}}
  textarea:focus{{outline:none;border-color:#C9A96E}}
  .addon-row{{display:flex;align-items:center;gap:14px;padding:14px 0;
              border-bottom:1px solid #1a1a1a;cursor:pointer}}
  .addon-row:last-child{{border-bottom:none}}
  .addon-row input[type=checkbox]{{width:18px;height:18px;accent-color:#C9A96E;cursor:pointer;flex-shrink:0}}
  .addon-info{{flex:1}}
  .addon-name{{font-size:14px;font-weight:600;color:#f0f0f0}}
  .addon-desc{{font-size:12px;color:#666;margin-top:2px;line-height:1.5}}
  .addon-price{{font-size:14px;font-weight:700;color:#C9A96E;white-space:nowrap;flex-shrink:0}}
  .total-bar{{background:#111;border:1px solid #C9A96E;border-radius:12px;padding:24px 28px}}
  .total-label{{font-size:13px;color:#888;text-transform:uppercase;letter-spacing:1px}}
  .total-amount{{font-size:42px;font-weight:900;color:#C9A96E;margin:6px 0}}
  .total-sub{{font-size:13px;color:#666}}
  .deposit-line{{margin-top:10px;font-size:14px;color:#aaa}}
  .deposit-line strong{{color:#fff}}
  input[type=text], input[type=email], input[type=tel]{{
    width:100%;background:#0d0d0d;border:1px solid #2a2a2a;border-radius:8px;
    padding:12px 14px;color:#f0f0f0;font-size:14px;font-family:inherit}}
  input:focus{{outline:none;border-color:#C9A96E}}
  .field-label{{font-size:12px;color:#888;text-transform:uppercase;letter-spacing:1px;
                margin-bottom:6px;display:block}}
  .field{{margin-bottom:16px}}
  .submit-btn{{width:100%;background:#C9A96E;color:#0d0d0d;border:none;border-radius:10px;
               padding:18px;font-size:17px;font-weight:800;cursor:pointer;letter-spacing:.3px;
               transition:opacity .15s}}
  .submit-btn:hover{{opacity:.9}}
  .success{{display:none;text-align:center;padding:40px 20px}}
  .success h2{{font-size:24px;font-weight:800;color:#C9A96E;margin-bottom:12px}}
  .success p{{color:#888;font-size:15px;line-height:1.7}}
</style>
</head>
<body>
<div class="header">
  <div>
    <div class="logo">Webby<span>Maya</span></div>
    <div class="header-sub">Your personalized website — {name}</div>
  </div>
</div>

<div class="container">
  <h1>Customize Your Website</h1>
  <p class="subtitle">Tell us what you love, what you'd change, and pick any add-ons — we'll show you the total right away.</p>

  <!-- Preview -->
  <div class="section">
    <div class="section-title">Your Preview</div>
    <iframe class="preview-frame" src="{preview_url}" loading="lazy"></iframe>
    <a class="preview-link" href="{preview_url}" target="_blank">Open full preview in new tab →</a>
  </div>

  <form id="intakeForm">
    <!-- Rating -->
    <div class="section">
      <div class="section-title">What did you think of the preview?</div>
      <div class="stars" id="stars">
        <span class="star" data-v="1" onclick="setStars(1)">★</span>
        <span class="star" data-v="2" onclick="setStars(2)">★</span>
        <span class="star" data-v="3" onclick="setStars(3)">★</span>
        <span class="star" data-v="4" onclick="setStars(4)">★</span>
        <span class="star" data-v="5" onclick="setStars(5)">★</span>
      </div>
      <input type="hidden" id="star_rating" name="star_rating" value="">
      <div class="field">
        <label class="field-label">Comments on the preview (optional)</label>
        <textarea name="preview_thoughts" rows="3" placeholder="What did you like? What felt off?"></textarea>
      </div>
    </div>

    <!-- Change requests -->
    <div class="section">
      <div class="section-title">What would you like to change or add?</div>
      <div class="field">
        <label class="field-label">Colors, content, photos, layout, tone — anything</label>
        <textarea name="change_requests" rows="5"
          placeholder="e.g. Change the background color to purple, add our logo, update the services list to include X, Y, Z, use our actual photos instead of stock..."></textarea>
      </div>
    </div>

    <!-- Add-ons -->
    <div class="section">
      <div class="section-title">Add-Ons — select what you need</div>
      <p style="font-size:13px;color:#666;margin-bottom:18px">Base package ($799) includes: 5 pages, mobile-ready design, Google Analytics, SSL, hosting for year 1, 30 days of support. Add anything below.</p>
      {addons_html}
    </div>

    <!-- Total -->
    <div class="total-bar" style="margin-bottom:20px">
      <div class="total-label">Your Investment</div>
      <div class="total-amount" id="totalDisplay">$799</div>
      <div class="total-sub">One-time · No monthly fees (unless maintenance selected)</div>
      <div class="deposit-line">To get started: <strong id="depositDisplay">$200 deposit</strong> · rest due on launch day</div>
    </div>

    <!-- Contact info -->
    <div class="section">
      <div class="section-title">Your Contact Info</div>
      <div class="field">
        <label class="field-label">Your name</label>
        <input type="text" name="contact_name" placeholder="First and last name" required>
      </div>
      <div class="field">
        <label class="field-label">Best email to reach you</label>
        <input type="email" name="contact_email" placeholder="you@example.com" required>
      </div>
      <div class="field">
        <label class="field-label">Phone / text (optional)</label>
        <input type="tel" name="contact_phone" placeholder="(215) 555-0000">
      </div>
      <div class="field">
        <label class="field-label">Best time to reach you (optional)</label>
        <input type="text" name="best_time" placeholder="e.g. weekday mornings, after 5pm">
      </div>
    </div>

    <input type="hidden" name="business_name" value="{name}">
    <input type="hidden" name="category" value="{category}">
    <input type="hidden" name="total_price" id="totalHidden" value="799">
    <input type="hidden" name="selected_addons" id="addonsHidden" value="">

    <button type="submit" class="submit-btn">Submit — Maya will be in touch within 24 hours</button>
  </form>

  <div class="success" id="successMsg">
    <h2>You're all set! 🎉</h2>
    <p>Maya has your details and will reach out within 24 hours to confirm everything and collect your deposit.<br><br>
    Questions before then? Email <a href="mailto:maya@webbymaya.com" style="color:#C9A96E">maya@webbymaya.com</a></p>
  </div>
</div>

<script>
{addons_js}
const BASE = {BASE_PRICE};

function calcTotal() {{
  let total = BASE;
  let selected = [];
  document.querySelectorAll('.addon-row input[type=checkbox]:checked').forEach(cb => {{
    total += parseInt(cb.value);
    selected.push(cb.id.replace('addon-',''));
  }});
  document.getElementById('totalDisplay').textContent = '$' + total.toLocaleString();
  document.getElementById('totalHidden').value = total;
  document.getElementById('addonsHidden').value = selected.join(',');
  // Deposit = 25% of total, min $200
  const deposit = Math.max(200, Math.round(total * 0.25 / 10) * 10);
  document.getElementById('depositDisplay').textContent = '$' + deposit.toLocaleString() + ' deposit';
}}

function setStars(n) {{
  document.querySelectorAll('.star').forEach((s,i) => {{
    s.classList.toggle('active', i < n);
  }});
  document.getElementById('star_rating').value = n;
}}

// Init total
calcTotal();

document.getElementById('intakeForm').addEventListener('submit', function(e) {{
  e.preventDefault();
  const data = Object.fromEntries(new FormData(this));
  fetch('{SUPABASE_URL}/rest/v1/intake_forms', {{
    method: 'POST',
    headers: {{
      'Content-Type':  'application/json',
      'apikey':        '{ANON_KEY}',
      'Authorization': 'Bearer {ANON_KEY}',
      'Prefer':        'return=minimal',
    }},
    body: JSON.stringify({{
      business:       data.business_name,
      category:       data.category,
      contact_name:   data.contact_name,
      contact_email:  data.contact_email,
      contact_phone:  data.contact_phone || '',
      best_time:      data.best_time || '',
      star_rating:    parseInt(data.star_rating) || 0,
      preview_thoughts: data.preview_thoughts || '',
      change_requests:  data.change_requests || '',
      selected_addons:  data.selected_addons || '',
      total_price:    parseInt(data.total_price) || {BASE_PRICE},
      source:         'intake_form',
    }}),
  }}).catch(() => {{}});
  this.style.display = 'none';
  document.getElementById('successMsg').style.display = 'block';
}});
</script>
</body>
</html>"""


def upload_intake_form(name: str, category: str, mockup_url: str = "") -> str:
    """Generate and upload the intake form. Returns public URL."""
    import urllib.request, urllib.error

    html  = generate_html(name, category, mockup_url)
    slug  = _slug(name)
    fname = f"intake-{slug}.html"
    data  = html.encode("utf-8")

    key   = SERVICE_KEY or ANON_KEY
    url   = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{fname}"

    for method in ("PUT", "POST"):
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type":  "text/html; charset=utf-8",
                "x-upsert":      "true",
            }
        )
        try:
            urllib.request.urlopen(req, timeout=20)
            public = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{fname}"
            print(f"  Intake form: {public}")
            return public
        except urllib.error.HTTPError as e:
            if e.code in (400, 409) and method == "POST":
                continue
            print(f"  [intake upload error] {e.code}: {e.read().decode()[:200]}")
    return ""


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--name",     required=True)
    p.add_argument("--category", default="")
    p.add_argument("--mockup",   default="")
    args = p.parse_args()
    url = upload_intake_form(args.name, args.category, args.mockup)
    print(url or "Upload failed")

"""
mockup_uploader.py — Upload a prospect mockup to Supabase Storage.
Returns a permanent public URL usable in emails.
Uses LoremFlickr for images (free, hotlink-OK, no API key).
"""
import re, urllib.request, urllib.error
from pathlib import Path

SUPABASE_URL = "https://ycsauzlqsjjbusugshpz.supabase.co"
SERVICE_KEY  = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inljc2F1emxxc2pqYnVzdWdzaHB6Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3OTQ2MzMxNCwiZXhwIjoyMDk1MDM5MzE0fQ.0qJY5I3THWHxPVVM49D8Ov1pmH91gMYb5bIXOOKJy1c"
BUCKET       = "mockups"

FLICKR_KEYS = {
    "nail salon":       ["nail,manicure",   "nails,salon"],
    "hair salon":       ["hair,salon",      "hairdresser"],
    "beauty salon":     ["beauty,salon",    "facial,spa"],
    "massage":          ["massage,spa",     "spa,wellness"],
    "restaurant":       ["restaurant,food", "fine,dining"],
    "cafe":             ["coffee,cafe",     "latte,art"],
    "bakery":           ["bakery,bread",    "pastry,cake"],
    "auto repair":      ["mechanic,car",    "auto,repair"],
    "landscaping":      ["garden,lawn",     "landscaping"],
    "cleaning service": ["cleaning,house",  "cleaning,service"],
    "photographer":     ["photographer",    "camera,photography"],
    "tattoo parlor":    ["tattoo,art",      "tattoo,studio"],
    "gym":              ["gym,fitness",     "workout,gym"],
    "personal trainer": ["personal,trainer","fitness,training"],
    "florist":          ["flowers,bouquet", "florist,shop"],
    "pet store":        ["dog,grooming",    "pet,animal"],
}
DEFAULT_KEYS = ["business,professional", "storefront,local"]

THEMES = {
    "nail salon":       {"accent":"#D4A8D0","dark":"#8B5E8B","bg":"#12080f","tag":"Beauty & Nails",
                         "tagline":"Professional Nail Care & Beauty Services",
                         "services":[("💅","Manicures & Pedicures"),("✨","Nail Art & Design"),("🛁","Spa Treatments")]},
    "hair salon":       {"accent":"#D4A87C","dark":"#8B6E3E","bg":"#120d08","tag":"Hair Salon",
                         "tagline":"Expert Hair Styling, Color & Care",
                         "services":[("✂️","Cuts & Styling"),("🎨","Color & Highlights"),("💆","Treatments")]},
    "beauty salon":     {"accent":"#D4A8C8","dark":"#8B5E80","bg":"#120810","tag":"Beauty Studio",
                         "tagline":"Head-to-Toe Beauty, All in One Place",
                         "services":[("💄","Makeup & Styling"),("💅","Nails & Waxing"),("🧖","Facials")]},
    "massage":          {"accent":"#84C8C8","dark":"#4A9999","bg":"#081212","tag":"Wellness",
                         "tagline":"Therapeutic Massage & Holistic Wellness",
                         "services":[("🤲","Swedish Massage"),("💪","Deep Tissue"),("🌡️","Hot Stone")]},
    "restaurant":       {"accent":"#E8A87C","dark":"#C07050","bg":"#120a05","tag":"Restaurant",
                         "tagline":"Fresh, Authentic Food Made With Heart",
                         "services":[("🍽️","Dine-In"),("📦","Takeout & Delivery"),("🥂","Private Events")]},
    "cafe":             {"accent":"#C8A882","dark":"#8B7055","bg":"#0f0a06","tag":"Cafe",
                         "tagline":"Your Neighborhood Coffee & Eatery",
                         "services":[("☕","Specialty Coffee"),("🥐","Fresh Pastries"),("🥗","Light Bites")]},
    "bakery":           {"accent":"#E8C87C","dark":"#B09040","bg":"#120e04","tag":"Bakery",
                         "tagline":"Handcrafted Baked Goods Made Fresh Daily",
                         "services":[("🎂","Custom Cakes"),("🍞","Fresh Breads"),("🧁","Pastries")]},
    "auto repair":      {"accent":"#6FA8DC","dark":"#3A6EA8","bg":"#060a12","tag":"Auto Repair",
                         "tagline":"Trusted Auto Repair & Maintenance",
                         "services":[("🔧","Oil Changes"),("🛞","Brakes & Tires"),("⚙️","Diagnostics")]},
    "landscaping":      {"accent":"#7EC87E","dark":"#3E8E3E","bg":"#060f06","tag":"Landscaping",
                         "tagline":"Beautiful Outdoor Spaces, All Year Round",
                         "services":[("🌿","Lawn Maintenance"),("🌸","Garden Design"),("❄️","Snow Removal")]},
    "cleaning service": {"accent":"#7AB8DC","dark":"#3A7EA8","bg":"#060a10","tag":"Cleaning",
                         "tagline":"Professional Cleaning You Can Trust",
                         "services":[("🏠","Residential"),("🏢","Commercial"),("📦","Move-In/Out")]},
    "photographer":     {"accent":"#C8B090","dark":"#887040","bg":"#0c0a08","tag":"Photography",
                         "tagline":"Professional Photography for Life's Moments",
                         "services":[("👤","Portraits"),("💒","Events & Weddings"),("📦","Commercial")]},
    "tattoo parlor":    {"accent":"#DC7A7A","dark":"#A84040","bg":"#100606","tag":"Tattoo Studio",
                         "tagline":"Custom Tattoos by Artists Who Care",
                         "services":[("🎨","Custom Designs"),("🔄","Cover-Ups"),("💎","Fine Line")]},
    "gym":              {"accent":"#E8A040","dark":"#B07020","bg":"#0e0900","tag":"Fitness",
                         "tagline":"Train Harder. Recover Better. Live Stronger.",
                         "services":[("🏋️","Open Gym"),("👥","Group Classes"),("🎯","Personal Training")]},
    "florist":          {"accent":"#E898B8","dark":"#B06080","bg":"#120810","tag":"Florist",
                         "tagline":"Fresh Florals for Every Occasion",
                         "services":[("💐","Custom Bouquets"),("💒","Wedding Florals"),("🚚","Same-Day Delivery")]},
    "pet store":        {"accent":"#80C880","dark":"#408840","bg":"#060e06","tag":"Pet Store",
                         "tagline":"Everything Your Pet Needs",
                         "services":[("🐕","Grooming"),("🛒","Food & Supplies"),("❤️","Expert Advice")]},
}
DEFAULT_THEME = {"accent":"#C9A96E","dark":"#8B6E3E","bg":"#0d0d0d","tag":"Local Business",
                 "tagline":"Serving Philadelphia With Quality & Care",
                 "services":[("⭐","Quality Service"),("🤝","Easy Online Booking"),("✅","Guaranteed Results")]}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

def _theme(category: str) -> dict:
    cat = (category or "").lower().strip()
    for k, t in THEMES.items():
        if k in cat or cat in k:
            return t
    return DEFAULT_THEME

def _flickr(category: str) -> list:
    cat = (category or "").lower().strip()
    for k, keys in FLICKR_KEYS.items():
        if k in cat or cat in k:
            return keys
    return DEFAULT_KEYS

def _flickr_url(query: str, w: int, h: int, lock: int) -> str:
    q = query.replace(" ", ",")
    return f"https://loremflickr.com/{w}/{h}/{q}?lock={lock}"


def generate_html_online(name: str, category: str, phone: str = "", city: str = "Philadelphia, PA") -> str:
    """Generate a full mockup HTML page using LoremFlickr images (hotlink-safe, no local files)."""
    theme  = _theme(category)
    fkeys  = _flickr(category)
    accent = theme["accent"]
    dark   = theme["dark"]
    bg     = theme["bg"]
    tag    = theme["tag"]
    tagline = theme["tagline"]
    services = theme["services"]

    phone_d    = phone or "(215) 555-0100"
    phone_href = re.sub(r"[^0-9+]", "", phone_d)
    city_d     = city or "Philadelphia, PA"
    short_city = city_d.split(",")[0]

    hero_url  = _flickr_url(fkeys[0], 1400, 900, 1)
    gal_urls  = [_flickr_url(fkeys[min(i, len(fkeys)-1)], 800, 600, i+10) for i in range(1, 4)]

    svc_html = "".join(f"""
      <div style="background:#111;border:1px solid #1e1e1e;border-radius:14px;padding:28px;transition:border-color .2s">
        <div style="font-size:26px;width:48px;height:48px;border-radius:12px;background:{accent}18;display:flex;align-items:center;justify-content:center;margin-bottom:16px">{ico}</div>
        <div style="font-size:16px;font-weight:700;color:#fff;margin-bottom:8px">{title}</div>
      </div>""" for ico, title in services)

    reviews = [
        ("Jennifer M.", 5, f"Absolutely love this place! I've been coming here for over a year and the quality never drops. My go-to in {short_city}."),
        ("Carlos R.",   5, f"Outstanding service from start to finish. Professional, friendly, and really knows what they're doing. Highly recommend."),
        ("Tamara L.",   4, "Great experience! They really take their time and make you feel welcome. Fair prices and excellent results."),
    ]
    review_html = "".join(f"""
      <div style="background:#111;border:1px solid #1e1e1e;border-radius:14px;padding:24px">
        <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px">
          <div style="width:40px;height:40px;border-radius:50%;background:linear-gradient(135deg,{accent},{dark});display:flex;align-items:center;justify-content:center;font-weight:700;color:#fff;font-size:14px;flex-shrink:0">{rev[0]}</div>
          <div>
            <div style="font-weight:700;color:#fff;font-size:14px">{rev}</div>
            <div style="color:#FBBC04;font-size:12px">{"★"*stars}{"☆"*(5-stars)}</div>
          </div>
        </div>
        <div style="font-size:14px;color:#888;line-height:1.7;font-style:italic">{text}</div>
      </div>""" for rev, stars, text in reviews)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name} — {short_city}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;background:{bg};color:#e2e2e2;line-height:1.65;overflow-x:hidden}}
img{{display:block;width:100%;object-fit:cover}}
a{{color:{accent};text-decoration:none}}
nav{{position:fixed;top:0;left:0;right:0;z-index:200;height:68px;display:flex;align-items:center;justify-content:space-between;padding:0 6%;background:rgba(10,10,10,.95);backdrop-filter:blur(16px);border-bottom:1px solid rgba(255,255,255,.07)}}
.nav-logo{{font-size:18px;font-weight:800;color:#fff}}.nav-logo em{{color:{accent};font-style:normal}}
.nav-cta{{background:{accent};color:#0d0d0d;padding:10px 22px;border-radius:8px;font-weight:700;font-size:14px}}
.hero{{min-height:100vh;display:flex;align-items:center;justify-content:center;text-align:center;position:relative;overflow:hidden;padding:100px 6% 80px}}
.hero-bg{{position:absolute;inset:0;background-image:url('{hero_url}');background-size:cover;background-position:center}}
.hero-bg::after{{content:'';position:absolute;inset:0;background:linear-gradient(to bottom,rgba(0,0,0,.55) 0%,{bg}cc 60%,{bg} 100%)}}
.hero-content{{position:relative;z-index:1;max-width:760px;margin:0 auto}}
h1{{font-size:clamp(2.4rem,7vw,5rem);font-weight:900;letter-spacing:-.04em;color:#fff;line-height:1.05;margin-bottom:20px;text-shadow:0 2px 24px rgba(0,0,0,.5)}}
h1 em{{color:{accent};font-style:normal}}
.hero-sub{{font-size:clamp(1rem,2.5vw,1.2rem);color:rgba(255,255,255,.75);max-width:540px;margin:0 auto 40px;line-height:1.6}}
.btn-primary{{background:{accent};color:#0d0d0d;padding:15px 36px;border-radius:10px;font-weight:800;font-size:15px;display:inline-flex;align-items:center;gap:8px}}
section{{padding:90px 6%}}
h2{{font-size:clamp(1.9rem,4.5vw,3rem);font-weight:900;letter-spacing:-.04em;color:#fff;line-height:1.1;margin-bottom:16px}}
.eyebrow{{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:{accent};margin-bottom:14px}}
.sub{{font-size:1.05rem;color:#888;max-width:560px;line-height:1.7;margin-bottom:48px}}
.grid-3{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:20px}}
.gallery{{display:grid;grid-template-columns:1.6fr 1fr 1fr;grid-template-rows:300px 220px;gap:10px;border-radius:16px;overflow:hidden;margin-top:-30px}}
.gal-item{{overflow:hidden}}.gal-item:first-child{{grid-row:1/3}}
.gal-item img{{width:100%;height:100%;object-fit:cover;transition:transform .6s}}.gal-item:hover img{{transform:scale(1.05)}}
.reviews-bg{{background:rgba(255,255,255,.02);border-top:1px solid #1e1e1e;border-bottom:1px solid #1e1e1e}}
footer{{background:#080808;border-top:1px solid #181818;padding:32px 6%;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:16px}}
.watermark{{position:fixed;bottom:18px;right:18px;background:rgba(13,13,13,.92);backdrop-filter:blur(10px);border:1px solid #222;border-radius:10px;padding:10px 14px;font-size:11px;color:#555}}
.watermark strong{{color:{accent}}}
@media(max-width:768px){{.gallery{{grid-template-columns:1fr 1fr;grid-template-rows:auto}}.gal-item:first-child{{grid-row:auto;grid-column:1/-1}}}}
</style>
</head>
<body>
<nav>
  <div class="nav-logo">{name.split()[0]}<em>{''.join(name.split()[1:]) or ''}</em></div>
  <a href="mailto:maya@webbymaya.com" class="nav-cta">Get a Quote</a>
</nav>

<section class="hero">
  <div class="hero-bg"></div>
  <div class="hero-content">
    <div style="display:inline-flex;align-items:center;gap:8px;background:rgba(255,255,255,.08);backdrop-filter:blur(8px);border:1px solid rgba(255,255,255,.15);border-radius:24px;padding:6px 16px;font-size:13px;color:rgba(255,255,255,.8);margin-bottom:28px">
      <span style="color:{accent}">{tag}</span> &nbsp;·&nbsp; {short_city}, PA
    </div>
    <h1>{name}</h1>
    <p class="hero-sub">{tagline}</p>
    <a href="mailto:maya@webbymaya.com" class="btn-primary">✉️ Get This Website</a>
  </div>
</section>

<section id="services">
  <p class="eyebrow">What We Do</p>
  <h2>Our Services</h2>
  <p class="sub">Everything you need, handled by professionals who take pride in their work.</p>
  <div class="grid-3">{svc_html}</div>
</section>

<section style="padding-top:0">
  <div class="gallery">
    <div class="gal-item"><img src="{gal_urls[0]}" alt="{name}" loading="lazy"></div>
    <div class="gal-item"><img src="{gal_urls[1]}" alt="{name}" loading="lazy"></div>
    <div class="gal-item"><img src="{gal_urls[2]}" alt="{name}" loading="lazy"></div>
  </div>
</section>

<section id="reviews" class="reviews-bg">
  <p class="eyebrow">What People Say</p>
  <h2>Google Reviews</h2>
  <p class="sub">Don't just take our word for it.</p>
  <div class="grid-3">{review_html}</div>
</section>

<section style="text-align:center">
  <p class="eyebrow">Ready to Get Started?</p>
  <h2>Get Your Website Today</h2>
  <p class="sub" style="margin:0 auto 36px">Starting at $799. Fully mobile-ready. Live in 2 weeks.</p>
  <a href="mailto:maya@webbymaya.com" class="btn-primary" style="margin:0 auto;display:inline-flex">✉️ Email Maya to Get Started</a>
</section>

<footer>
  <div style="font-size:16px;font-weight:800;color:#fff">{name.split()[0]}<em style="color:{accent};font-style:normal">{''.join(name.split()[1:]) or ''}</em></div>
  <span style="font-size:12px;color:#444">{city_d}</span>
  <div style="font-size:11px;color:#444;border:1px solid #1c1c1c;border-radius:6px;padding:5px 12px;background:#0a0a0a">
    Preview by <a href="https://webbymaya.com" style="color:{accent};font-weight:600">WebByMaya.com</a>
  </div>
</footer>

<div class="watermark">Site preview by <strong>WebByMaya</strong></div>
<script>
document.querySelector('nav').style.background='rgba(10,10,10,0)';
window.addEventListener('scroll',()=>{{
  document.querySelector('nav').style.background=window.scrollY>60?'rgba(10,10,10,.95)':'rgba(10,10,10,0)';
}});
</script>
</body></html>"""


def upload_mockup(name: str, category: str, phone: str = "", city: str = "Philadelphia, PA") -> str:
    """
    Generate a full mockup page and upload to Supabase Storage.
    Returns the public URL, or '' on failure.
    """
    biz_slug = _slug(name)
    filename = f"{biz_slug}.html"
    html     = generate_html_online(name, category, phone, city)
    encoded  = html.encode("utf-8")

    url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{filename}"
    req = urllib.request.Request(
        url, data=encoded, method="POST",
        headers={
            "Authorization": f"Bearer {SERVICE_KEY}",
            "Content-Type":  "text/html;charset=utf-8",
            "x-upsert":      "true",
        })
    try:
        urllib.request.urlopen(req, timeout=20)
        return f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{filename}"
    except Exception as exc:
        print(f"  [mockup upload] {exc}")
        return ""


if __name__ == "__main__":
    import sys
    name     = sys.argv[1] if len(sys.argv) > 1 else "Test Salon"
    category = sys.argv[2] if len(sys.argv) > 2 else "hair salon"
    phone    = sys.argv[3] if len(sys.argv) > 3 else ""
    url = upload_mockup(name, category, phone)
    if url:
        print(f"Mockup URL: {url}")
    else:
        print("Upload failed.")

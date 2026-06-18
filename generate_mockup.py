#!/usr/bin/env python3
"""
generate_mockup.py — WebByMaya Mockup Generator
Generates a polished, photo-rich one-page website preview for a prospect.

USAGE
    python3 generate_mockup.py "Fancy Nail Salon" --category "nail salon" --phone "215-555-0100" --city "Philadelphia, PA"
    python3 generate_mockup.py "Mike's Auto" --category "auto repair" --open
"""

import argparse, json, os, re, subprocess, urllib.request
from pathlib import Path

SCRIPT_DIR  = Path(__file__).parent
MOCKUPS_DIR = SCRIPT_DIR / "mockups"
IMGS_DIR    = MOCKUPS_DIR / "img"
MOCKUPS_DIR.mkdir(exist_ok=True)
IMGS_DIR.mkdir(exist_ok=True)

# ── LoremFlickr keyword sets per category ─────────────────────────────────────
# loremflickr.com/{w}/{h}/{keywords}?lock={n} — free, no API key, hotlink OK,
# ?lock= makes it deterministic so same category always shows same photo.

FLICKR_KEYS = {
    "nail salon":       ["nail,manicure",    "nails,salon",      "manicure,beauty",  "nail,art"],
    "hair salon":       ["hair,salon",       "hairdresser",      "hair,color",       "hair,style"],
    "beauty salon":     ["beauty,salon",     "facial,spa",       "skincare,beauty",  "makeup,salon"],
    "massage":          ["massage,spa",      "massage,therapy",  "spa,wellness",     "relaxation,spa"],
    "restaurant":       ["restaurant,food",  "fine,dining",      "food,plating",     "restaurant,interior"],
    "cafe":             ["coffee,cafe",      "latte,art",        "coffee,shop",      "espresso,cafe"],
    "bakery":           ["bakery,bread",     "pastry,cake",      "bakery,fresh",     "cake,dessert"],
    "auto repair":      ["mechanic,car",     "auto,repair",      "car,garage",       "mechanic,shop"],
    "landscaping":      ["garden,lawn",      "landscaping",      "lawn,care",        "garden,nature"],
    "cleaning service": ["cleaning,house",   "cleaning,service", "clean,professional","maid,cleaning"],
    "photographer":     ["photographer",     "camera,photography","photo,studio",    "portrait,photography"],
    "tattoo parlor":    ["tattoo,art",       "tattoo,studio",    "ink,tattoo",       "tattoo,design"],
    "gym":              ["gym,fitness",      "workout,gym",      "weights,fitness",  "exercise,gym"],
    "personal trainer": ["personal,trainer", "fitness,training", "workout,coach",    "exercise,training"],
    "florist":          ["flowers,bouquet",  "florist,shop",     "flower,arrangement","roses,flowers"],
    "pet store":        ["dog,grooming",     "pet,animal",       "dog,pet",          "cat,pet"],
}

DEFAULT_KEYS = ["business,professional", "office,team", "storefront,local", "service,professional"]

def get_flickr_keys(category: str) -> list:
    cat = category.lower().strip()
    for key, keywords in FLICKR_KEYS.items():
        if key in cat or cat in key:
            return keywords
    return DEFAULT_KEYS

PEXELS_KEY = os.environ.get("PEXELS_API_KEY", "")

def pexels_fetch(query: str, idx: int, dest: Path):
    """Search Pexels for query, download the idx-th result to dest. Returns local rel path."""
    if dest.exists():
        return f"img/{dest.name}"
    if not PEXELS_KEY:
        return None
    try:
        clean = query.replace(",", " ").replace(" ", "+")
        search_url = f"https://api.pexels.com/v1/search?query={clean}&per_page=4&page=1&orientation=landscape"
        result = subprocess.run(
            ["curl", "-s", "-H", f"Authorization: {PEXELS_KEY}", search_url],
            capture_output=True, timeout=15
        )
        data    = json.loads(result.stdout)
        photos  = data.get("photos", [])
        if not photos:
            return None
        photo   = photos[min(idx, len(photos)-1)]
        img_url = photo["src"]["large2x"]
        dl = subprocess.run(["curl", "-sL", "-o", str(dest), img_url], timeout=30)
        if dl.returncode != 0 or not dest.exists():
            return None
        print(f"  photo: {dest.name}  ({photo['photographer']})")
        return f"img/{dest.name}"
    except Exception as e:
        print(f"  pexels fetch failed ({query}): {e}")
        return None

# ── Category themes ────────────────────────────────────────────────────────────

THEMES = {
    "nail salon":       {"accent":"#D4A8D0","dark":"#8B5E8B","bg":"#12080f","emoji":"💅","tag":"Beauty & Nails",
                         "tagline":"Professional Nail Care & Beauty Services",
                         "services":[("💅","Manicures & Pedicures","Classic, gel, and acrylic nail services for every occasion."),
                                     ("✨","Nail Art & Design","Custom nail art from minimalist to full expression."),
                                     ("🛁","Spa Treatments","Relaxing hand and foot treatments that restore and refresh.")]},
    "hair salon":       {"accent":"#D4A87C","dark":"#8B6E3E","bg":"#120d08","emoji":"✂️","tag":"Hair Salon",
                         "tagline":"Expert Hair Styling, Color & Care",
                         "services":[("✂️","Cuts & Styling","Precision cuts and blowouts tailored to your face and lifestyle."),
                                     ("🎨","Color & Highlights","Balayage, highlights, full color — we get it right."),
                                     ("💆","Treatments","Deep conditioning, keratin, and scalp treatments.")]},
    "beauty salon":     {"accent":"#D4A8C8","dark":"#8B5E80","bg":"#120810","emoji":"💄","tag":"Beauty Studio",
                         "tagline":"Head-to-Toe Beauty, All in One Place",
                         "services":[("💄","Makeup & Styling","Everyday looks and special occasion glam."),
                                     ("💅","Nails & Waxing","Full nail services and smooth waxing treatments."),
                                     ("🧖","Facials & Skincare","Customized facials for every skin type.")]},
    "massage":          {"accent":"#84C8C8","dark":"#4A9999","bg":"#081212","emoji":"🧘","tag":"Wellness & Massage",
                         "tagline":"Therapeutic Massage & Holistic Wellness",
                         "services":[("🤲","Swedish Massage","Full-body relaxation to melt away tension and stress."),
                                     ("💪","Deep Tissue","Targeted work on chronic muscle tension and pain."),
                                     ("🌡️","Hot Stone Therapy","Warm stones combined with massage for deep relaxation.")]},
    "restaurant":       {"accent":"#E8A87C","dark":"#C07050","bg":"#120a05","emoji":"🍽️","tag":"Restaurant",
                         "tagline":"Fresh, Authentic Food Made With Heart",
                         "services":[("🍽️","Dine-In Experience","A warm, inviting atmosphere for any occasion."),
                                     ("📦","Takeout & Delivery","Your favorites, ready when you are."),
                                     ("🥂","Private Events","Catering and private dining for groups of all sizes.")]},
    "cafe":             {"accent":"#C8A882","dark":"#8B7055","bg":"#0f0a06","emoji":"☕","tag":"Cafe",
                         "tagline":"Your Neighborhood Coffee & Eatery",
                         "services":[("☕","Specialty Coffee","Espresso drinks, cold brew, and seasonal specials."),
                                     ("🥐","Fresh Pastries","Baked in-house daily — croissants, muffins, and more."),
                                     ("🥗","Light Bites","Sandwiches, salads, and breakfast bowls done right.")]},
    "bakery":           {"accent":"#E8C87C","dark":"#B09040","bg":"#120e04","emoji":"🧁","tag":"Bakery",
                         "tagline":"Handcrafted Baked Goods Made Fresh Daily",
                         "services":[("🎂","Custom Cakes","Wedding, birthday, and celebration cakes to order."),
                                     ("🍞","Fresh Breads","Artisan loaves baked from scratch every morning."),
                                     ("🧁","Pastries & Sweets","Cupcakes, cookies, tarts, and seasonal treats.")]},
    "auto repair":      {"accent":"#6FA8DC","dark":"#3A6EA8","bg":"#060a12","emoji":"🔧","tag":"Auto Repair",
                         "tagline":"Trusted Auto Repair & Maintenance — Done Right",
                         "services":[("🔧","Oil Changes & Tune-Ups","Fast, reliable service to keep your car running smooth."),
                                     ("🛞","Brakes & Tires","Inspections, replacements, and alignments you can trust."),
                                     ("⚙️","Diagnostics & Repair","Engine, transmission, electrical — we fix it all.")]},
    "landscaping":      {"accent":"#7EC87E","dark":"#3E8E3E","bg":"#060f06","emoji":"🌿","tag":"Landscaping",
                         "tagline":"Beautiful Outdoor Spaces, All Year Round",
                         "services":[("🌿","Lawn Maintenance","Regular mowing, edging, and seasonal cleanup."),
                                     ("🌸","Garden Design","Custom planting plans that transform your yard."),
                                     ("❄️","Snow Removal","Fast, reliable snow and ice removal when you need it.")]},
    "cleaning service": {"accent":"#7AB8DC","dark":"#3A7EA8","bg":"#060a10","emoji":"✨","tag":"Cleaning",
                         "tagline":"Professional Cleaning You Can Actually Trust",
                         "services":[("🏠","Residential Cleaning","Regular and deep cleans tailored to your home."),
                                     ("🏢","Commercial Cleaning","Office and business cleaning on your schedule."),
                                     ("📦","Move-In / Move-Out","Thorough cleaning for transitions and new beginnings.")]},
    "photographer":     {"accent":"#C8B090","dark":"#887040","bg":"#0c0a08","emoji":"📸","tag":"Photography",
                         "tagline":"Professional Photography for Life's Biggest Moments",
                         "services":[("👤","Portraits & Headshots","Personal and professional portraits that stand out."),
                                     ("💒","Events & Weddings","Capturing memories you'll treasure forever."),
                                     ("📦","Commercial Photography","Product, branding, and real estate photography.")]},
    "tattoo parlor":    {"accent":"#DC7A7A","dark":"#A84040","bg":"#100606","emoji":"🎨","tag":"Tattoo Studio",
                         "tagline":"Custom Tattoos by Artists Who Care About Their Work",
                         "services":[("🎨","Custom Designs","Original artwork drawn just for you, no flash."),
                                     ("🔄","Cover-Ups","Transform old or unwanted tattoos into something you love."),
                                     ("💎","Fine Line & Detail","Delicate, precision work for the most intricate designs.")]},
    "gym":              {"accent":"#E8A040","dark":"#B07020","bg":"#0e0900","emoji":"💪","tag":"Fitness",
                         "tagline":"Train Harder. Recover Better. Live Stronger.",
                         "services":[("🏋️","Open Gym","State-of-the-art equipment available 24/7."),
                                     ("👥","Group Classes","HIIT, yoga, spin, and more — coached every session."),
                                     ("🎯","Personal Training","One-on-one programming built around your goals.")]},
    "personal trainer": {"accent":"#E8A040","dark":"#B07020","bg":"#0e0900","emoji":"💪","tag":"Personal Training",
                         "tagline":"Results-Driven Training, Built Around You",
                         "services":[("🎯","1-on-1 Training","Customized programs that actually move the needle."),
                                     ("🥗","Nutrition Coaching","Fueling your body to match your training."),
                                     ("💻","Online Programs","Train anywhere with personalized remote coaching.")]},
    "florist":          {"accent":"#E898B8","dark":"#B06080","bg":"#120810","emoji":"🌸","tag":"Florist",
                         "tagline":"Fresh Florals for Every Occasion",
                         "services":[("💐","Custom Bouquets","Handcrafted arrangements for any occasion or feeling."),
                                     ("💒","Wedding Florals","Full wedding floral design, from altar to centerpieces."),
                                     ("🚚","Same-Day Delivery","Fresh flowers delivered across the city, fast.")]},
    "pet store":        {"accent":"#80C880","dark":"#408840","bg":"#060e06","emoji":"🐾","tag":"Pet Store",
                         "tagline":"Everything Your Pet Needs — All in One Place",
                         "services":[("🐕","Grooming Services","Baths, haircuts, and spa treatments for your pup."),
                                     ("🛒","Food & Supplies","Premium pet food, toys, and accessories in stock."),
                                     ("❤️","Expert Advice","Our team knows pets — ask us anything.")]},
}

DEFAULT_THEME = {"accent":"#C9A96E","dark":"#8B6E3E","bg":"#0d0d0d","emoji":"⭐","tag":"Local Business",
                 "tagline":"Serving the Community With Quality & Care",
                 "services":[("⭐","Quality Service","Professional, reliable service every single time."),
                              ("🤝","Easy Online Booking","Fill out our quick form — we'll handle everything from there."),
                              ("✅","Satisfaction Guaranteed","We're not done until you're 100% happy.")]}

REVIEW_NAMES = [
    ("Jennifer M.", 5, "Absolutely love this place! I've been coming here for over a year and the quality never drops. Highly recommend to anyone looking for the best in {city}."),
    ("Carlos R.", 5, "Outstanding service from start to finish. The team is professional, friendly, and really knows what they're doing. My go-to in {city}."),
    ("Tamara L.", 4, "Great experience! They really take their time and make you feel welcome. Fair prices and excellent results. Will definitely be back."),
]

def get_theme(category: str) -> dict:
    cat = category.lower().strip()
    for key, theme in THEMES.items():
        if key in cat or cat in key:
            return theme
    return DEFAULT_THEME

def slug(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')

def stars(n: int) -> str:
    return "★" * n + "☆" * (5 - n)

def generate_html(name: str, category: str, phone: str, city: str, theme: dict, fkeys: list, address: str = "") -> str:
    phone_display = phone or "(215) 555-0100"
    phone_href    = re.sub(r'[^0-9+]', '', phone_display)
    city_display  = city or "Philadelphia, PA"
    short_city    = city_display.split(',')[0]
    import json as _json
    json_name     = _json.dumps(name)
    _map_q        = (address or city_display).replace(' ', '+').replace(',', '%2C').replace('#', '%23')
    accent        = theme["accent"]
    dark          = theme["dark"]
    bg            = theme["bg"]
    emoji         = theme["emoji"]
    services      = theme["services"]

    biz_slug   = slug(name)
    queries    = fkeys  # one search query string per photo slot
    hero_src   = pexels_fetch(queries[0], 0, IMGS_DIR / f"{biz_slug}-hero.jpg")
    gal_srcs   = [pexels_fetch(queries[i], i, IMGS_DIR / f"{biz_slug}-g{i}.jpg") for i in range(1, 4)]
    hero_img   = hero_src or ""   # empty = CSS gradient fallback (see below)
    gal_imgs   = [s or hero_img for s in gal_srcs]
    no_photos  = not hero_img
    # Pre-computed onerror handlers (can't use backslash inside f-string expressions in Python < 3.12)
    _fb0 = f"this.onerror=null;this.style.display='none';this.parentElement.style.background='linear-gradient(135deg,{dark},{bg})'"
    _fb1 = f"this.onerror=null;this.style.display='none';this.parentElement.style.background='linear-gradient(135deg,{accent}33,{bg})'"
    _fb2 = f"this.onerror=null;this.style.display='none';this.parentElement.style.background='linear-gradient(135deg,{dark},{accent}44)'"
    _fba = f"this.onerror=null;this.style.display='none';this.parentElement.style.background='linear-gradient(135deg,{dark},{bg})'"
    reviews    = [(n, s, t.replace("{city}", short_city)) for n, s, t in REVIEW_NAMES]
    svc_html   = "".join(f"""
        <div class="svc-card" data-reveal data-delay="{i+1}">
          <div class="svc-icon">{ico}</div>
          <h3>{title}</h3>
          <p>{desc}</p>
        </div>""" for i, (ico, title, desc) in enumerate(services))
    review_html = "".join(f"""
        <div class="review-card" data-reveal data-delay="{i+1}">
          <div class="review-top">
            <div class="reviewer-avatar">{reviewer[0]}</div>
            <div>
              <div class="reviewer-name">{reviewer}</div>
              <div class="review-stars" style="color:#FBBC04">{stars(rating)}</div>
            </div>
            <img src="https://upload.wikimedia.org/wikipedia/commons/thumb/5/53/Google_%22G%22_Logo.svg/20px-Google_%22G%22_Logo.svg.png"
                 style="margin-left:auto;opacity:.7;width:16px;height:16px" alt="Google">
          </div>
          <p class="review-text">{text}</p>
        </div>""" for i, (reviewer, rating, text) in enumerate(reviews))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name} — {short_city}</title>
<style>
  *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
  :root{{
    --a:{accent};--d:{dark};--bg:{bg};
    --surface:#111;--border:#1e1e1e;--text:#e2e2e2;--muted:#888;
  }}
  html{{scroll-behavior:smooth}}
  body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;
        background:var(--bg);color:var(--text);line-height:1.65;overflow-x:hidden}}
  img{{display:block;width:100%;object-fit:cover}}
  a{{color:var(--a);text-decoration:none}}

  /* ── NAV ── */
  nav{{
    position:fixed;top:0;left:0;right:0;z-index:200;
    height:68px;display:flex;align-items:center;justify-content:space-between;
    padding:0 6%;
    background:rgba(10,10,10,0);
    border-bottom:1px solid transparent;
    transition:background .3s,border-color .3s;
  }}
  nav.scrolled{{background:rgba(10,10,10,.95);backdrop-filter:blur(16px);border-color:rgba(255,255,255,.07)}}
  .nav-logo{{font-size:18px;font-weight:800;color:#fff;letter-spacing:-.5px}}
  .nav-logo em{{color:var(--a);font-style:normal}}
  .nav-links{{display:flex;gap:28px;font-size:14px;color:#aaa}}
  .nav-links a{{color:#aaa;transition:.15s}}.nav-links a:hover{{color:#fff}}
  .nav-cta{{
    background:var(--a);color:#0d0d0d;
    padding:10px 22px;border-radius:8px;
    font-weight:700;font-size:14px;
    transition:opacity .15s,transform .15s;
    white-space:nowrap;
  }}
  .nav-cta:hover{{opacity:.88;transform:translateY(-1px)}}

  /* ── HERO ── */
  .hero{{
    min-height:100vh;
    display:flex;align-items:center;justify-content:center;
    text-align:center;
    position:relative;overflow:hidden;
    padding:100px 6% 80px;
  }}
  .hero-bg{{
    position:absolute;inset:0;
    {'background-image:url("' + hero_img + '");' if hero_img else f'background:linear-gradient(135deg,{dark} 0%,{bg} 100%);'}
    background-size:cover;background-position:center;
    animation:kenBurns 24s ease-in-out infinite;
  }}
  .hero-bg::after{{
    content:'';position:absolute;inset:0;
    background:linear-gradient(
      to bottom,
      rgba(0,0,0,.55) 0%,
      {bg}cc 60%,
      {bg} 100%
    );
  }}
  .hero-content{{position:relative;z-index:1;max-width:760px;margin:0 auto}}
  .hero-badge{{
    display:inline-flex;align-items:center;gap:8px;
    background:rgba(255,255,255,.08);backdrop-filter:blur(8px);
    border:1px solid rgba(255,255,255,.15);
    border-radius:24px;padding:6px 16px;
    font-size:13px;color:rgba(255,255,255,.8);
    margin-bottom:28px;letter-spacing:.03em;
  }}
  .hero-badge span{{color:var(--a)}}
  .hero h1{{
    font-size:clamp(2.4rem,7vw,5rem);
    font-weight:900;letter-spacing:-.04em;
    color:#fff;line-height:1.05;
    margin-bottom:20px;
    text-shadow:0 2px 24px rgba(0,0,0,.5);
  }}
  .hero h1 em{{color:var(--a);font-style:normal}}
  .hero-sub{{
    font-size:clamp(1rem,2.5vw,1.2rem);
    color:rgba(255,255,255,.75);
    max-width:540px;margin:0 auto 40px;
    line-height:1.6;
  }}
  .hero-btns{{display:flex;gap:14px;justify-content:center;flex-wrap:wrap}}
  .btn-primary{{
    background:var(--a);color:#0d0d0d;
    padding:15px 36px;border-radius:10px;
    font-weight:800;font-size:15px;
    transition:opacity .15s,transform .15s;
    display:inline-flex;align-items:center;gap:8px;
  }}
  .btn-primary:hover{{opacity:.88;transform:translateY(-2px)}}
  .btn-outline{{
    border:1.5px solid rgba(255,255,255,.3);color:#fff;
    padding:15px 36px;border-radius:10px;
    font-weight:600;font-size:15px;
    transition:border-color .15s,color .15s;
    display:inline-flex;align-items:center;gap:8px;
  }}
  .btn-outline:hover{{border-color:var(--a);color:var(--a)}}

  /* ── TRUST STRIP ── */
  .trust{{
    background:rgba(255,255,255,.03);
    border-top:1px solid var(--border);
    border-bottom:1px solid var(--border);
    padding:24px 6%;
    display:flex;justify-content:center;gap:0;flex-wrap:wrap;
  }}
  .trust-item{{
    text-align:center;padding:8px 36px;
    border-right:1px solid var(--border);
  }}
  .trust-item:last-child{{border-right:none}}
  .trust-num{{font-size:26px;font-weight:900;color:var(--a);letter-spacing:-.02em}}
  .trust-label{{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin-top:3px}}

  /* ── SECTIONS ── */
  section{{padding:90px 6%}}
  .section-eyebrow{{
    font-size:11px;font-weight:700;
    text-transform:uppercase;letter-spacing:.12em;
    color:var(--a);margin-bottom:14px;
  }}
  h2{{
    font-size:clamp(1.9rem,4.5vw,3rem);
    font-weight:900;letter-spacing:-.04em;
    color:#fff;line-height:1.1;
    margin-bottom:16px;
  }}
  .section-sub{{
    font-size:1.05rem;color:var(--muted);
    max-width:560px;line-height:1.7;
    margin-bottom:56px;
  }}

  /* ── SERVICES ── */
  .services-grid{{
    display:grid;
    grid-template-columns:repeat(auto-fit,minmax(260px,1fr));
    gap:20px;
  }}
  .svc-card{{
    background:var(--surface);
    border:1px solid var(--border);
    border-radius:14px;padding:32px 28px;
    transition:border-color .2s,transform .2s;
  }}
  .svc-card:hover{{border-color:var(--a);transform:translateY(-4px)}}
  .svc-icon{{
    font-size:28px;
    width:52px;height:52px;border-radius:12px;
    background:{accent}18;
    display:flex;align-items:center;justify-content:center;
    margin-bottom:20px;
  }}
  .svc-card h3{{font-size:17px;font-weight:700;color:#fff;margin-bottom:10px}}
  .svc-card p{{font-size:14px;color:#777;line-height:1.65}}

  /* ── PHOTO GALLERY ── */
  .gallery-section{{background:var(--bg);padding-top:0}}
  .gallery-grid{{
    display:grid;
    grid-template-columns:1.6fr 1fr 1fr;
    grid-template-rows:320px 240px;
    gap:10px;border-radius:16px;overflow:hidden;
  }}
  .gallery-item{{position:relative;overflow:hidden}}
  .gallery-item img{{
    width:100%;height:100%;object-fit:cover;
    transition:transform .6s ease;
    background:linear-gradient(135deg,{dark},{bg});
  }}
  .gallery-item:hover img{{transform:scale(1.05)}}
  .gallery-item:first-child{{grid-row:1/3}}
  .gallery-item::after{{
    content:'';position:absolute;inset:0;
    background:linear-gradient(135deg,{accent}22,transparent);
    pointer-events:none;
  }}

  /* ── ABOUT ── */
  .about-inner{{
    display:grid;grid-template-columns:1fr 1fr;
    gap:64px;align-items:center;
  }}
  .about-img{{
    border-radius:16px;overflow:hidden;
    height:440px;position:relative;
  }}
  .about-img img{{height:100%;width:100%;object-fit:cover}}
  .about-img::before{{
    content:'';position:absolute;inset:0;z-index:1;
    border:1px solid {accent}40;border-radius:16px;pointer-events:none;
  }}
  .about-text h2{{margin-bottom:20px}}
  .about-text p{{color:#999;margin-bottom:18px;line-height:1.8;font-size:15px}}
  .about-tags{{display:flex;gap:10px;flex-wrap:wrap;margin-top:28px}}
  .about-tag{{
    background:{accent}15;border:1px solid {accent}40;
    color:var(--a);border-radius:20px;
    padding:6px 16px;font-size:13px;font-weight:600;
  }}

  /* ── REVIEWS ── */
  .reviews-bg{{background:rgba(255,255,255,.02);border-top:1px solid var(--border);border-bottom:1px solid var(--border)}}
  .reviews-grid{{
    display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));
    gap:20px;
  }}
  .review-card{{
    background:var(--surface);
    border:1px solid var(--border);
    border-radius:14px;padding:28px 24px;
  }}
  .review-top{{display:flex;align-items:center;gap:14px;margin-bottom:16px}}
  .reviewer-avatar{{
    width:42px;height:42px;border-radius:50%;
    background:linear-gradient(135deg,{accent},{dark});
    display:flex;align-items:center;justify-content:center;
    font-size:16px;font-weight:700;color:#fff;flex-shrink:0;
  }}
  .reviewer-name{{font-weight:700;color:#fff;font-size:14px}}
  .review-stars{{font-size:13px;margin-top:2px;letter-spacing:1px}}
  .review-text{{font-size:14px;color:#888;line-height:1.7;font-style:italic}}

  /* ── CTA BAND ── */
  .cta-band{{
    position:relative;overflow:hidden;
    text-align:center;padding:100px 6%;
  }}
  .cta-band-bg{{
    position:absolute;inset:0;
    background-image:url('{gal_imgs[2]}');
    background-size:cover;background-position:center;
    filter:brightness(.25) saturate(.5);
  }}
  .cta-band-overlay{{
    position:absolute;inset:0;
    background:radial-gradient(ellipse 80% 80% at 50% 50%,{accent}25 0%,{bg}ee 100%);
  }}
  .cta-band-content{{position:relative;z-index:1}}
  .cta-band h2{{margin-bottom:14px}}
  .cta-band p{{color:#999;margin-bottom:36px;max-width:480px;margin-left:auto;margin-right:auto}}

  /* ── CONTACT ── */
  .contact-grid{{
    display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
    gap:18px;margin-top:40px;
  }}
  .contact-card{{
    background:var(--surface);border:1px solid var(--border);
    border-radius:12px;padding:28px;text-align:center;
  }}
  .contact-icon{{font-size:28px;margin-bottom:12px}}
  .contact-label{{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px}}
  .contact-val{{color:#ddd;font-weight:700;font-size:15px}}
  .hours-row{{display:flex;justify-content:space-between;font-size:13px;padding:5px 0;border-bottom:1px solid var(--border)}}
  .hours-row:last-child{{border-bottom:none}}
  .hours-day{{color:var(--muted)}} .hours-time{{color:#ddd;font-weight:600}}

  /* ── INQUIRY FORM ── */
  .inquiry-section{{
    background:linear-gradient(135deg,{dark}22,{bg});
    border-top:1px solid {accent}33;
    padding:64px 6%;text-align:center;
  }}
  .inquiry-section h2{{font-size:clamp(22px,3vw,32px);color:#fff;margin-bottom:8px}}
  .inquiry-section p{{color:var(--muted);margin-bottom:32px;font-size:15px}}
  .inquiry-form{{
    max-width:480px;margin:0 auto;
    display:flex;flex-direction:column;gap:14px;
  }}
  .inquiry-form input,.inquiry-form textarea{{
    background:#111;border:1px solid #2a2a2a;border-radius:8px;
    padding:14px 16px;color:#fff;font-size:15px;font-family:inherit;
    outline:none;transition:border .2s;
  }}
  .inquiry-form input:focus,.inquiry-form textarea:focus{{border-color:{accent};}}
  .inquiry-form textarea{{resize:vertical;min-height:80px}}
  .inquiry-submit{{
    background:{accent};color:{bg};
    font-weight:800;font-size:16px;
    padding:16px;border:none;border-radius:8px;cursor:pointer;
    transition:opacity .2s;
  }}
  .inquiry-submit:hover{{opacity:.88}}
  .inquiry-success{{display:none;color:{accent};font-weight:700;font-size:17px;margin-top:12px}}

  /* ── FOOTER ── */
  footer{{
    background:#080808;
    border-top:1px solid #181818;
    padding:32px 6%;
    display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:16px;
  }}
  .footer-logo{{font-size:16px;font-weight:800;color:#fff}}
  .footer-logo em{{color:var(--a);font-style:normal}}
  .footer-links{{display:flex;gap:24px;font-size:13px;color:#555}}
  .footer-badge{{
    font-size:11px;color:#444;
    border:1px solid #1c1c1c;border-radius:6px;
    padding:5px 12px;background:#0a0a0a;
  }}
  .footer-badge a{{color:{accent};font-weight:600}}

  /* ── ANIMATIONS ── */
  @keyframes kenBurns {{
    0%   {{ transform:scale(1)    translate(0,0); }}
    33%  {{ transform:scale(1.09) translate(-1.5%,-1%); }}
    66%  {{ transform:scale(1.06) translate(1%,.5%); }}
    100% {{ transform:scale(1)    translate(0,0); }}
  }}
  @keyframes fadeUp {{
    from {{ opacity:0; transform:translateY(32px); }}
    to   {{ opacity:1; transform:translateY(0); }}
  }}
  @keyframes ctaPulse {{
    0%,100% {{ box-shadow:0 0 0 0 {accent}66; }}
    55%     {{ box-shadow:0 0 0 14px {accent}00; }}
  }}
  .hero-content > * {{
    opacity:0;
    animation:fadeUp .75s cubic-bezier(.22,.68,0,1.2) forwards;
  }}
  .hero-content .hero-badge {{ animation-delay:.15s }}
  .hero-content h1           {{ animation-delay:.3s }}
  .hero-content .hero-sub    {{ animation-delay:.45s }}
  .hero-content .hero-btns   {{ animation-delay:.6s }}
  .inquiry-submit            {{ animation:ctaPulse 2.8s ease-in-out infinite; }}
  [data-reveal] {{
    opacity:0;
    transform:translateY(40px);
    transition:opacity .7s ease, transform .7s ease;
  }}
  [data-reveal].visible {{
    opacity:1;
    transform:translateY(0);
  }}
  [data-reveal][data-delay="1"] {{ transition-delay:.08s }}
  [data-reveal][data-delay="2"] {{ transition-delay:.18s }}
  [data-reveal][data-delay="3"] {{ transition-delay:.28s }}

  /* ── WATERMARK ── */
  .watermark{{
    position:fixed;bottom:18px;right:18px;z-index:300;
    background:rgba(13,13,13,.92);backdrop-filter:blur(10px);
    border:1px solid #222;border-radius:10px;
    padding:10px 14px;font-size:11px;color:#555;
    box-shadow:0 4px 24px rgba(0,0,0,.4);
  }}
  .watermark strong{{color:{accent}}}

  /* ── PROGRESS BAR ── */
  #progress-bar{{
    position:fixed;top:0;left:0;z-index:1000;
    height:3px;width:0%;
    background:linear-gradient(90deg,{accent},{dark});
    transition:width .08s linear;pointer-events:none;
  }}

  /* ── STICKY CTA ── */
  #sticky-cta{{
    position:fixed;bottom:0;left:0;right:0;z-index:400;
    background:rgba(8,8,8,.96);backdrop-filter:blur(16px);
    border-top:1px solid {accent}33;
    padding:14px 6%;
    display:flex;align-items:center;justify-content:space-between;gap:16px;
    transform:translateY(100%);
    transition:transform .4s cubic-bezier(.22,.68,0,1.2);
  }}
  #sticky-cta.show{{ transform:translateY(0); }}
  .sticky-cta-text{{ font-size:14px;color:#888; }}
  .sticky-cta-text strong{{ color:#fff; }}
  .sticky-cta-btn{{
    background:{accent};color:{bg};
    font-weight:800;font-size:14px;
    padding:11px 24px;border-radius:8px;
    white-space:nowrap;flex-shrink:0;
    transition:opacity .15s;
  }}
  .sticky-cta-btn:hover{{ opacity:.88; }}

  /* ── HAMBURGER / MOBILE MENU ── */
  .nav-hamburger{{
    display:none;background:none;border:none;
    cursor:pointer;padding:8px;gap:5px;
    flex-direction:column;align-items:flex-end;
  }}
  .nav-hamburger span{{
    display:block;height:2px;background:#fff;border-radius:2px;
    transition:transform .3s,opacity .3s,width .3s;
  }}
  .nav-hamburger span:nth-child(1){{ width:22px; }}
  .nav-hamburger span:nth-child(2){{ width:16px; }}
  .nav-hamburger span:nth-child(3){{ width:22px; }}
  .nav-hamburger.open span:nth-child(1){{ transform:translateY(7px) rotate(45deg);width:22px; }}
  .nav-hamburger.open span:nth-child(2){{ opacity:0; }}
  .nav-hamburger.open span:nth-child(3){{ transform:translateY(-7px) rotate(-45deg);width:22px; }}
  #mobile-menu{{
    position:fixed;top:68px;left:0;right:0;z-index:150;
    background:rgba(8,8,8,.98);backdrop-filter:blur(20px);
    border-bottom:1px solid #1e1e1e;
    max-height:0;overflow:hidden;
    transition:max-height .4s ease;
  }}
  #mobile-menu.open{{ max-height:320px; }}
  #mobile-menu a{{
    display:block;padding:16px 6%;
    color:#aaa;font-size:17px;font-weight:600;
    border-bottom:1px solid #151515;
    transition:color .15s,background .15s;
  }}
  #mobile-menu a:hover{{ color:var(--a);background:rgba(255,255,255,.02); }}

  /* ── LIGHTBOX ── */
  #lightbox{{
    position:fixed;inset:0;z-index:900;
    background:rgba(0,0,0,.93);backdrop-filter:blur(10px);
    display:flex;align-items:center;justify-content:center;
    opacity:0;pointer-events:none;
    transition:opacity .3s;
  }}
  #lightbox.open{{ opacity:1;pointer-events:all; }}
  #lightbox-img{{
    max-width:90vw;max-height:88vh;
    object-fit:contain;border-radius:10px;
    transform:scale(.9);
    transition:transform .35s cubic-bezier(.22,.68,0,1.2);
    display:block;
  }}
  #lightbox.open #lightbox-img{{ transform:scale(1); }}
  #lightbox-close{{
    position:absolute;top:20px;right:24px;
    background:rgba(255,255,255,.1);border:none;
    color:#fff;font-size:24px;
    width:44px;height:44px;border-radius:50%;
    cursor:pointer;display:flex;align-items:center;justify-content:center;
    transition:background .2s;
  }}
  #lightbox-close:hover{{ background:rgba(255,255,255,.2); }}
  .gallery-item img{{ cursor:zoom-in; }}

  /* ── RESPONSIVE ── */
  @media(max-width:768px){{
    .nav-links,.nav-cta{{display:none}}
    .nav-hamburger{{display:flex}}
    .about-inner{{grid-template-columns:1fr}}
    .gallery-grid{{grid-template-columns:1fr 1fr;grid-template-rows:auto}}
    .gallery-item:first-child{{grid-row:auto;grid-column:1/-1}}
    .trust-item{{padding:8px 20px}}
    .sticky-cta-text{{display:none}}
    #sticky-cta{{justify-content:center}}
  }}
</style>
</head>
<body>

<div id="progress-bar"></div>

<nav id="nav">
  <div class="nav-logo">{name.split()[0]}<em>{''.join(name.split()[1:]) or ''}</em></div>
  <div class="nav-links">
    <a href="#services">Services</a>
    <a href="#about">About</a>
    <a href="#reviews">Reviews</a>
    <a href="#contact">Contact</a>
  </div>
  <a href="tel:{phone_href}" class="nav-cta">📞 Call Now</a>
  <button class="nav-hamburger" id="hamburger" aria-label="Menu">
    <span></span><span></span><span></span>
  </button>
</nav>

<div id="mobile-menu">
  <a href="#services" class="mobile-link">Services</a>
  <a href="#about" class="mobile-link">About</a>
  <a href="#reviews" class="mobile-link">Reviews</a>
  <a href="#contact" class="mobile-link">Contact</a>
  <a href="#get-started" class="mobile-link" style="color:var(--a)">Get Started →</a>
</div>

<section class="hero">
  <div class="hero-bg" id="hero-bg"></div>
  <div class="hero-content">
    <div class="hero-badge">{emoji} <span>{theme["tag"]}</span> &nbsp;·&nbsp; {short_city}, PA</div>
    <h1>{name}</h1>
    <p class="hero-sub">{theme["tagline"]} in {short_city}</p>
    <div class="hero-btns">
      <a href="tel:{phone_href}" class="btn-primary">📞 {phone_display}</a>
      <a href="#services" class="btn-outline">See Our Services</a>
    </div>
  </div>
</section>

<div class="trust" data-reveal>
  <div class="trust-item"><div class="trust-num" data-count="500">0</div><div class="trust-label">Happy Customers</div></div>
  <div class="trust-item"><div class="trust-num" data-count="10">0</div><div class="trust-label">Years in {short_city}</div></div>
  <div class="trust-item"><div class="trust-num">5★</div><div class="trust-label">Google Rating</div></div>
  <div class="trust-item"><div class="trust-num">Same Day</div><div class="trust-label">Response</div></div>
</div>

<section id="services">
  <p class="section-eyebrow" data-reveal>What We Do</p>
  <h2 data-reveal>Our Services</h2>
  <p class="section-sub" data-reveal>Everything you need, handled by professionals who take pride in their work.</p>
  <div class="services-grid">{svc_html}</div>
</section>

{'<section class="gallery-section"><div class="gallery-grid">' +
 f'<div class="gallery-item"><img src="{gal_imgs[0]}" alt="{name}" loading="lazy" onerror="{_fb0}"></div>' +
 f'<div class="gallery-item"><img src="{gal_imgs[1]}" alt="{name}" loading="lazy" onerror="{_fb1}"></div>' +
 f'<div class="gallery-item"><img src="{gal_imgs[2]}" alt="{name}" loading="lazy" onerror="{_fb2}"></div>' +
 '</div></section>' if not no_photos else ''}

<section id="about" style="background:rgba(255,255,255,.015)">
  <div class="about-inner" {'style="grid-template-columns:1fr"' if no_photos else ''}>
    {'<div class="about-img"><img src="' + gal_imgs[1] + f'" alt="About {name}" loading="lazy" onerror="{_fba}"></div>' if not no_photos else ''}
    <div class="about-text">
      <p class="section-eyebrow">Our Story</p>
      <h2>About {name}</h2>
      <p>We've been proudly serving the {short_city} community with top-quality {category or "service"} for years. From day one, our focus has been simple: do great work and treat every customer like family.</p>
      <p>Whether you're a first-time visitor or a longtime regular, you'll always get our best. That's the standard we hold ourselves to — and why {short_city} keeps coming back to us.</p>
      <div class="about-tags">
        <span class="about-tag">Locally Owned</span>
        <span class="about-tag">{short_city} Based</span>
        <span class="about-tag">Satisfaction Guaranteed</span>
      </div>
    </div>
  </div>
</section>

<section id="reviews" class="reviews-bg">
  <p class="section-eyebrow" data-reveal>What People Say</p>
  <h2 data-reveal>Google Reviews</h2>
  <p class="section-sub" data-reveal>Don't just take our word for it — here's what our customers have to say.</p>
  <div class="reviews-grid">{review_html}</div>
</section>

<section class="cta-band">
  <div class="cta-band-bg"></div>
  <div class="cta-band-overlay"></div>
  <div class="cta-band-content" data-reveal>
    <p class="section-eyebrow">Ready to Get Started?</p>
    <h2>Get Started Today</h2>
    <p>Fill out our quick form and we'll take it from there — no calls needed.</p>
    <a href="https://webbymaya.com/book" class="btn-primary" style="margin:0 auto;display:inline-flex">Fill Out Our Form →</a>
  </div>
</section>

<section id="contact">
  <p class="section-eyebrow">Find Us</p>
  <h2>Hours & Contact</h2>
  <div class="contact-grid">
    <div class="contact-card">
      <div class="contact-icon">📞</div>
      <div class="contact-label">Phone</div>
      <div class="contact-val"><a href="tel:{phone_href}" style="color:#fff">{phone_display}</a></div>
    </div>
    <div class="contact-card">
      <div class="contact-icon">📍</div>
      <div class="contact-label">Location</div>
      <div class="contact-val">{address if address else city_display}</div>
    </div>
    <div class="contact-card" style="grid-column:span 2">
      <div class="contact-icon">🕐</div>
      <div class="contact-label" style="margin-bottom:16px">Hours</div>
      <div class="hours-row"><span class="hours-day">Monday – Friday</span><span class="hours-time">9:00 AM – 7:00 PM</span></div>
      <div class="hours-row"><span class="hours-day">Saturday</span><span class="hours-time">9:00 AM – 5:00 PM</span></div>
      <div class="hours-row"><span class="hours-day">Sunday</span><span class="hours-time">Closed</span></div>
    </div>
  </div>
  <div style="margin-top:32px;border-radius:14px;overflow:hidden;border:1px solid var(--border);height:280px" data-reveal>
    <iframe
      src="https://maps.google.com/maps?q={_map_q}&output=embed&z=15"
      width="100%" height="100%" style="border:0;display:block"
      allowfullscreen loading="lazy" referrerpolicy="no-referrer-when-downgrade">
    </iframe>
  </div>
</section>

<section class="inquiry-section" id="get-started">
  <p class="section-eyebrow">Free Preview — No Commitment</p>
  <h2>Want this site for your business?</h2>
  <p>Leave your name and email — Maya will reach out within 24 hours.</p>
  <form class="inquiry-form" id="inquiryForm">
    <input type="text" name="name" placeholder="Your name" required />
    <input type="email" name="email" placeholder="Your email" required />
    <textarea name="message" placeholder="Anything you'd like to add (optional)"></textarea>
    <button type="submit" class="inquiry-submit">Yes, I'm Interested →</button>
  </form>
  <div class="inquiry-success" id="inquirySuccess">✅ Got it! Maya will be in touch soon.</div>
</section>

<footer>
  <div class="footer-logo">{name.split()[0]}<em>{''.join(name.split()[1:]) or ''}</em></div>
  <div class="footer-links">
    <span>© 2026 {name}</span>
    <span>{city_display}</span>
    <a href="tel:{phone_href}">{phone_display}</a>
  </div>
  <div class="footer-badge">Preview by <a href="https://webbymaya.com" target="_blank">WebByMaya.com</a></div>
</footer>

<div class="watermark">Site mockup by <strong>WebByMaya</strong></div>

<div id="lightbox">
  <button id="lightbox-close" aria-label="Close">✕</button>
  <img id="lightbox-img" src="" alt="Gallery photo">
</div>

<div id="sticky-cta">
  <div class="sticky-cta-text">Like what you see? <strong>Get this site for your business.</strong></div>
  <a href="#get-started" class="sticky-cta-btn">Get Started →</a>
</div>

<script>
  // Nav scroll effect
  const nav = document.getElementById('nav');
  window.addEventListener('scroll', () => {{
    nav.classList.toggle('scrolled', window.scrollY > 60);
  }}, {{passive:true}});

  // Scroll progress bar
  const progressBar = document.getElementById('progress-bar');
  window.addEventListener('scroll', () => {{
    const pct = window.scrollY / (document.body.scrollHeight - window.innerHeight) * 100;
    progressBar.style.width = pct + '%';
  }}, {{passive:true}});

  // Sticky CTA (shows after scrolling past hero)
  const stickyCta   = document.getElementById('sticky-cta');
  const heroSection = document.querySelector('.hero');
  const ctaObserver = new IntersectionObserver(([e]) => {{
    stickyCta.classList.toggle('show', !e.isIntersecting);
  }}, {{threshold:0}});
  ctaObserver.observe(heroSection);

  // Hamburger / mobile menu
  const hamburger   = document.getElementById('hamburger');
  const mobileMenu  = document.getElementById('mobile-menu');
  hamburger.addEventListener('click', () => {{
    hamburger.classList.toggle('open');
    mobileMenu.classList.toggle('open');
  }});
  document.querySelectorAll('.mobile-link').forEach(a => {{
    a.addEventListener('click', () => {{
      hamburger.classList.remove('open');
      mobileMenu.classList.remove('open');
    }});
  }});

  // Gallery lightbox
  const lightbox     = document.getElementById('lightbox');
  const lightboxImg  = document.getElementById('lightbox-img');
  const lightboxClose = document.getElementById('lightbox-close');
  document.querySelectorAll('.gallery-item img').forEach(img => {{
    img.addEventListener('click', () => {{
      lightboxImg.src = img.src;
      lightbox.classList.add('open');
      document.body.style.overflow = 'hidden';
    }});
  }});
  function closeLightbox() {{
    lightbox.classList.remove('open');
    document.body.style.overflow = '';
  }}
  lightboxClose.addEventListener('click', closeLightbox);
  lightbox.addEventListener('click', e => {{ if (e.target === lightbox) closeLightbox(); }});
  document.addEventListener('keydown', e => {{ if (e.key === 'Escape') closeLightbox(); }});

  // Scroll reveals via IntersectionObserver
  const revealObserver = new IntersectionObserver((entries) => {{
    entries.forEach(el => {{
      if (el.isIntersecting) {{
        el.target.classList.add('visible');
        revealObserver.unobserve(el.target);
      }}
    }});
  }}, {{threshold: 0.12}});
  document.querySelectorAll('[data-reveal]').forEach(el => revealObserver.observe(el));

  // Animated counters
  function animateCount(el, target, suffix) {{
    const dur = 1400;
    const start = performance.now();
    const update = (now) => {{
      const p = Math.min((now - start) / dur, 1);
      const ease = 1 - Math.pow(1 - p, 3);
      el.textContent = Math.floor(ease * target) + suffix;
      if (p < 1) requestAnimationFrame(update);
    }};
    requestAnimationFrame(update);
  }}
  const counterObserver = new IntersectionObserver((entries) => {{
    entries.forEach(entry => {{
      if (entry.isIntersecting) {{
        entry.target.querySelectorAll('[data-count]').forEach(el => {{
          animateCount(el, parseInt(el.dataset.count), '+');
        }});
        counterObserver.unobserve(entry.target);
      }}
    }});
  }}, {{threshold: 0.5}});
  document.querySelectorAll('.trust').forEach(el => counterObserver.observe(el));

  // Inquiry form → Supabase
  document.getElementById('inquiryForm').addEventListener('submit', async (e) => {{
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.target));
    data.business_name = {json_name};
    try {{
      await fetch('https://ycsauzlqsjjbusugshpz.supabase.co/rest/v1/mockup_inquiries', {{
        method: 'POST',
        headers: {{
          'Content-Type': 'application/json',
          'apikey': 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inljc2F1emxxc2pqYnVzdWdzaHB6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk0NjMzMTQsImV4cCI6MjA5NTAzOTMxNH0._rjYuGZch-CA4sfm2rV3lvs_ixDcQfNFg90KWsbe1HI',
          'Authorization': 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inljc2F1emxxc2pqYnVzdWdzaHB6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk0NjMzMTQsImV4cCI6MjA5NTAzOTMxNH0._rjYuGZch-CA4sfm2rV3lvs_ixDcQfNFg90KWsbe1HI',
          'Prefer': 'return=minimal'
        }},
        body: JSON.stringify(data)
      }});
      e.target.style.display = 'none';
      document.getElementById('inquirySuccess').style.display = 'block';
    }} catch(err) {{
      alert('Something went wrong — please email maya@webbymaya.com directly.');
    }}
  }});
</script>
</body>
</html>"""

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    parser.add_argument("--category", default="")
    parser.add_argument("--phone",    default="")
    parser.add_argument("--city",     default="Philadelphia, PA")
    parser.add_argument("--open",     action="store_true")
    args = parser.parse_args()

    theme  = get_theme(args.category)
    fkeys  = get_flickr_keys(args.category)
    html   = generate_html(args.name, args.category, args.phone, args.city, theme, fkeys)
    filename = slug(args.name) + ".html"
    out_path = MOCKUPS_DIR / filename
    out_path.write_text(html, encoding="utf-8")
    print(f"\nMockup saved: {out_path}")
    print(f"Dashboard URL: http://localhost:8787/mockup/{filename}")
    if args.open:
        import subprocess
        subprocess.run(["open", str(out_path)])
    return out_path

if __name__ == "__main__":
    main()

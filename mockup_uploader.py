"""
mockup_uploader.py — WebByMaya Mockup Generator & Uploader
Generates a premium one-page site preview and uploads to Supabase Storage.

Image strategy:
  1. Pexels API (PEXELS_API_KEY in env) → download + upload to Supabase as persistent images
  2. Fallback: picsum.photos (Lorem Picsum) — reliable, beautiful, no API key needed
  Never uses loremflickr (unreliable).
"""
import hashlib, json, os, re, urllib.request, urllib.error
from pathlib import Path

SUPABASE_URL = "https://ycsauzlqsjjbusugshpz.supabase.co"
SERVICE_KEY  = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inljc2F1emxxc2pqYnVzdWdzaHB6Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3OTQ2MzMxNCwiZXhwIjoyMDk1MDM5MzE0fQ.0qJY5I3THWHxPVVM49D8Ov1pmH91gMYb5bIXOOKJy1c"
BUCKET       = "mockups"
PEXELS_KEY   = os.environ.get("PEXELS_API_KEY", "")
PIXABAY_KEY  = os.environ.get("PIXABAY_API_KEY", "")

# ---------------------------------------------------------------------------
# Category config — theme colors + services + Pexels search queries
# ---------------------------------------------------------------------------

CATS = {
    "nail salon": {
        "accent": "#D4A8D0", "dark": "#8B5E8B", "bg": "#12080f",
        "tag": "Beauty & Nails", "tagline": "Professional Nail Care & Beauty Services",
        "services": [
            ("💅", "Manicures & Pedicures",  "Classic, gel, and acrylic nails with attention to detail on every visit."),
            ("✨", "Nail Art & Design",       "Custom designs, ombré, chrome, and seasonal patterns by our skilled artists."),
            ("🛁", "Spa Treatments",          "Relaxing foot soaks, callus removal, and moisturizing treatments."),
            ("💆", "Waxing & Brow Services", "Quick, precise waxing for brows, lip, and more in a clean environment."),
        ],
        "queries": ["nail salon manicure", "nail art beauty", "spa nail care"],
        "included": ["Online booking calendar", "Service menu with pricing", "Photo gallery of work", "Google Maps & directions", "Mobile-friendly design", "Contact form"],
        "reviews": [
            ("Jennifer M.", 5, "Best nail salon in the area. The technicians are meticulous and always do exactly what I ask. My nails have never looked better!"),
            ("Keisha T.",   5, "Came in for a last-minute appointment and they fit me right in. Clean, professional, and my gel manicure is still perfect two weeks later."),
            ("Sandra L.",   4, "Love coming here. Relaxing vibe and great work every time. The nail art designs are stunning."),
        ],
    },
    "hair salon": {
        "accent": "#D4A87C", "dark": "#8B6E3E", "bg": "#120d08",
        "tag": "Hair Salon", "tagline": "Expert Hair Styling, Color & Care",
        "services": [
            ("✂️", "Cuts & Styling",       "Precision cuts for all hair types, from bobs to layers, blowouts to braids."),
            ("🎨", "Color & Highlights",   "Balayage, ombré, full color, and glossing treatments by certified colorists."),
            ("💆", "Treatments & Masks",   "Keratin, deep conditioning, and bond repair treatments for healthy hair."),
            ("👰", "Special Occasions",    "Updos, bridal styles, and event-ready hair for any occasion."),
        ],
        "queries": ["hair salon styling", "hair color highlights", "hair stylist salon"],
        "included": ["Online appointment booking", "Service & pricing menu", "Before & after gallery", "Google Maps & hours", "Mobile-friendly site", "Contact form"],
        "reviews": [
            ("Maria G.",    5, "Absolutely amazing! I've been going here for two years and the color work is consistently beautiful. Worth every penny."),
            ("Danielle R.", 5, "Finally found a salon that understands my curly hair. They gave me the best cut I've ever had. I won't go anywhere else."),
            ("Tara B.",     4, "Great atmosphere, talented stylists, and very reasonable prices. My highlights came out exactly how I wanted."),
        ],
    },
    "barber shop": {
        "accent": "#7AB8DC", "dark": "#3A7EA8", "bg": "#06090f",
        "tag": "Barbershop", "tagline": "Sharp Cuts. Clean Fades. Classic Barber Service.",
        "services": [
            ("✂️", "Haircuts & Fades",    "Precision cuts, skin fades, taper fades, and classic scissor cuts for any style."),
            ("🪒", "Beard Trims & Shaves","Hot towel straight-razor shaves and beard sculpting with expert technique."),
            ("👦", "Kids & Student Cuts", "Patient, skilled cuts for kids and student discounts available."),
            ("💈", "Line-Ups & Designs",  "Crisp edge line-ups and custom hair designs to express your personal style."),
        ],
        "queries": ["barbershop haircut fade", "barber shop men grooming", "fade haircut barber"],
        "included": ["Walk-in waitlist tracker", "Service menu & pricing", "Staff profiles", "Google Maps & hours", "Mobile-friendly site", "Contact & booking form"],
        "reviews": [
            ("Marcus J.",  5, "Best barber in the city. My fade is always on point and the atmosphere is great. Been coming here for 3 years."),
            ("Devon W.",   5, "Quick, clean, and always exact. I've sent my whole family here and nobody's been disappointed."),
            ("Amir S.",    4, "Great cuts, great conversation. This is exactly what a barbershop should be."),
        ],
    },
    "barbershop": {
        "accent": "#7AB8DC", "dark": "#3A7EA8", "bg": "#06090f",
        "tag": "Barbershop", "tagline": "Sharp Cuts. Clean Fades. Classic Barber Service.",
        "services": [
            ("✂️", "Haircuts & Fades",    "Precision cuts, skin fades, taper fades, and classic scissor cuts for any style."),
            ("🪒", "Beard Trims & Shaves","Hot towel straight-razor shaves and beard sculpting with expert technique."),
            ("👦", "Kids & Student Cuts", "Patient, skilled cuts for kids and student discounts available."),
            ("💈", "Line-Ups & Designs",  "Crisp edge line-ups and custom hair designs to express your personal style."),
        ],
        "queries": ["barbershop haircut fade", "barber shop men grooming", "fade haircut barber"],
        "included": ["Walk-in waitlist tracker", "Service menu & pricing", "Staff profiles", "Google Maps & hours", "Mobile-friendly site", "Contact & booking form"],
        "reviews": [
            ("Marcus J.",  5, "Best barber in the city. My fade is always on point and the atmosphere is great. Been coming here for 3 years."),
            ("Devon W.",   5, "Quick, clean, and always exact. I've sent my whole family here and nobody's been disappointed."),
            ("Amir S.",    4, "Great cuts, great conversation. This is exactly what a barbershop should be."),
        ],
    },
    "restaurant": {
        "accent": "#E8A87C", "dark": "#C07050", "bg": "#120a05",
        "tag": "Restaurant", "tagline": "Fresh, Authentic Food Made With Heart",
        "services": [
            ("🍽️", "Dine-In Experience",  "A welcoming atmosphere where every dish is made fresh and every guest is family."),
            ("📦", "Takeout & Delivery",  "Order online or by phone. Hot, fresh food ready fast for pickup or delivery."),
            ("🥂", "Private Events",       "Private dining room available for birthdays, corporate lunches, and celebrations."),
            ("☕", "Catering",             "Full-service catering for events big and small — menus customized for you."),
        ],
        "queries": ["restaurant fine dining food", "restaurant interior dining room", "fresh food restaurant"],
        "included": ["Online menu with photos", "Reservation booking widget", "Private events page", "Google Maps & hours", "Mobile-friendly site", "Contact & inquiry form"],
        "reviews": [
            ("Carlos R.",  5, "Hands down the best food in the neighborhood. Everything is fresh and the portions are generous. We come every week."),
            ("Patricia H.",5, "We booked the private room for my husband's birthday and it was perfect. The food and service exceeded every expectation."),
            ("James T.",   4, "Great spot for a casual dinner. The food is consistently good and the staff is friendly and attentive."),
        ],
    },
    "cafe": {
        "accent": "#C8A882", "dark": "#8B7055", "bg": "#0f0a06",
        "tag": "Cafe", "tagline": "Your Neighborhood Coffee & Eatery",
        "services": [
            ("☕", "Specialty Coffee",   "Expertly pulled espresso, pour-overs, and lattes with locally roasted beans."),
            ("🥐", "Fresh Pastries",     "Croissants, muffins, scones, and daily specials baked fresh every morning."),
            ("🥗", "Light Bites & Lunch","Sandwiches, grain bowls, soups, and seasonal plates made with local ingredients."),
            ("📱", "Online Orders",      "Order ahead on our website — skip the line and grab your order on the go."),
        ],
        "queries": ["coffee shop latte art cafe", "cozy cafe interior coffee", "cafe espresso coffee shop"],
        "included": ["Online ordering menu", "Loyalty program page", "Daily specials section", "Google Maps & hours", "Mobile-friendly site", "Contact & catering form"],
        "reviews": [
            ("Rachel S.",  5, "My morning routine starts here. The latte art is stunning and the almond croissants are life-changing."),
            ("Tom B.",     5, "The best remote work spot in the city. Great wifi, great coffee, and the staff always remember my order."),
            ("Lily K.",    4, "Came in for a quick lunch and stayed two hours. Delicious sandwiches and the vibe is exactly what I needed."),
        ],
    },
    "bakery": {
        "accent": "#E8C87C", "dark": "#B09040", "bg": "#120e04",
        "tag": "Bakery", "tagline": "Handcrafted Baked Goods Made Fresh Daily",
        "services": [
            ("🎂", "Custom Cakes",       "Birthday, wedding, and celebration cakes designed to your exact specifications."),
            ("🍞", "Fresh Breads",       "Sourdough, multigrain, ciabatta, and seasonal specialty loaves baked daily."),
            ("🧁", "Pastries & Cookies", "Croissants, danishes, macarons, brownies, and more rotating daily treats."),
            ("📦", "Wholesale & Catering","Supply your café or event — custom orders with advance notice."),
        ],
        "queries": ["bakery fresh bread pastry", "bakery cakes pastries shop", "artisan bakery croissant"],
        "included": ["Custom order request form", "Menu with seasonal items", "Photo gallery of creations", "Google Maps & hours", "Mobile-friendly site", "Wholesale inquiry form"],
        "reviews": [
            ("Anna P.",    5, "The sourdough bread here is unbelievable. I drive 20 minutes just to get it. Everything they make is exceptional."),
            ("David K.",   5, "Ordered a custom birthday cake and it was the most beautiful cake I've ever seen. Tasted even better than it looked."),
            ("Maria S.",   4, "The croissants are buttery and perfect. This place is a gem. Glad I found it!"),
        ],
    },
    "auto repair": {
        "accent": "#6FA8DC", "dark": "#3A6EA8", "bg": "#060a12",
        "tag": "Auto Repair", "tagline": "Trusted Auto Repair & Maintenance",
        "services": [
            ("🔧", "Oil Changes & Tune-Ups",  "Fast oil changes, filter replacements, and full tune-ups to keep you running smooth."),
            ("🛞", "Brakes & Tires",           "Brake inspections, pad replacements, tire rotations, and new tire mounting."),
            ("⚙️", "Engine & Transmission",   "Diagnostic scans, engine repair, and transmission service by certified mechanics."),
            ("💡", "Electrical & AC",          "Battery testing, alternator repair, AC recharge, and electrical diagnostics."),
        ],
        "queries": ["auto repair mechanic garage", "car repair shop mechanic", "automotive repair service center"],
        "included": ["Service menu & pricing", "Appointment scheduling", "Before & after repair photos", "Google Maps & directions", "Mobile-friendly site", "Quote request form"],
        "reviews": [
            ("Robert M.",  5, "Fair prices and honest mechanics. They told me exactly what my car needed and didn't try to upsell me on anything extra."),
            ("Diana L.",   5, "Got my brakes done here and they were thorough, fast, and affordable. This is my shop from now on."),
            ("Eric T.",    4, "Went in for an oil change and they caught a brake issue I didn't know about. Saved me a lot of money in the long run."),
        ],
    },
    "cleaning service": {
        "accent": "#7AB8DC", "dark": "#3A7EA8", "bg": "#060a10",
        "tag": "Cleaning", "tagline": "Professional Cleaning You Can Trust",
        "services": [
            ("🏠", "Residential Cleaning",  "Weekly, bi-weekly, and one-time deep cleans for homes of all sizes."),
            ("🏢", "Commercial Cleaning",   "Office, retail, and commercial space cleaning on your schedule."),
            ("📦", "Move-In / Move-Out",    "Thorough cleaning for tenants, landlords, and real estate agents."),
            ("✨", "Deep Clean & Sanitize", "Full sanitization services including appliances, cabinets, and hard-to-reach areas."),
        ],
        "queries": ["professional cleaning service home", "house cleaning service team", "commercial cleaning office"],
        "included": ["Online booking & scheduling", "Service packages & pricing", "Before & after gallery", "Google Maps & coverage area", "Mobile-friendly site", "Quote request form"],
        "reviews": [
            ("Nicole T.",  5, "They left my house spotless. The team was professional, on time, and very thorough. I'm booking them monthly now."),
            ("Kevin B.",   5, "Hired them for a move-out clean and got our full deposit back. They're worth every dollar."),
            ("Susan W.",   4, "Reliable and thorough. I've used a lot of cleaning services and this is the best one I've found."),
        ],
    },
    "spa": {
        "accent": "#84C8C8", "dark": "#4A9999", "bg": "#081212",
        "tag": "Spa & Wellness", "tagline": "Relax. Restore. Renew.",
        "services": [
            ("🧖", "Facials & Skincare",     "Custom facials, microdermabrasion, and chemical peels for glowing skin."),
            ("🤲", "Massage Therapy",         "Swedish, deep tissue, hot stone, and prenatal massage by licensed therapists."),
            ("💅", "Nail & Beauty Services", "Manicures, pedicures, waxing, and lash services in a relaxing environment."),
            ("🌿", "Wellness Packages",       "Couples spa days, bridal packages, and full-day wellness retreats."),
        ],
        "queries": ["luxury spa wellness relaxation", "day spa massage treatment", "spa beauty wellness center"],
        "included": ["Spa menu with pricing", "Online package booking", "Gift card sales page", "Google Maps & hours", "Mobile-friendly site", "Contact & event inquiry form"],
        "reviews": [
            ("Michelle R.", 5, "This spa is a true sanctuary. I leave feeling completely refreshed every single time. The staff is incredible."),
            ("Lauren H.",   5, "Booked the couples package for our anniversary and it was absolutely magical. We're already planning our next visit."),
            ("Teresa K.",   4, "Wonderful facials and very knowledgeable estheticians. My skin has never looked better."),
        ],
    },
    "massage": {
        "accent": "#84C8C8", "dark": "#4A9999", "bg": "#081212",
        "tag": "Massage Therapy", "tagline": "Therapeutic Massage & Holistic Wellness",
        "services": [
            ("🤲", "Swedish Massage",      "A relaxing, full-body massage to reduce stress and improve circulation."),
            ("💪", "Deep Tissue",          "Targeted pressure on chronic muscle tension, injury recovery, and knots."),
            ("🌡️","Hot Stone Therapy",    "Heated basalt stones to melt away muscle tension and restore energy flow."),
            ("🤰", "Prenatal Massage",     "Safe, gentle massage designed specifically for expecting mothers."),
        ],
        "queries": ["massage therapy wellness spa", "massage therapist relaxation", "therapeutic massage treatment"],
        "included": ["Online appointment booking", "Treatment menu & duration", "Therapist profiles", "Google Maps & hours", "Mobile-friendly site", "New client intake form"],
        "reviews": [
            ("Amanda S.",  5, "I've been dealing with chronic back pain for years and this massage therapist has changed my life. Highly recommend."),
            ("Brian T.",   5, "Booked a deep tissue session and left feeling like a new person. The therapist really listens and customizes the session."),
            ("Lisa M.",    4, "Very professional and therapeutic. The hot stone massage is worth every penny."),
        ],
    },
    "florist": {
        "accent": "#E898B8", "dark": "#B06080", "bg": "#120810",
        "tag": "Florist", "tagline": "Fresh Florals for Every Occasion",
        "services": [
            ("💐", "Custom Bouquets",       "Hand-arranged fresh flower bouquets for any occasion, same-day available."),
            ("💒", "Wedding Florals",        "Full wedding floral services — bridal bouquets, centerpieces, ceremony arches."),
            ("🚚", "Same-Day Delivery",      "Local flower delivery throughout the area, Monday through Saturday."),
            ("🎁", "Subscription & Gifts",  "Weekly or monthly fresh flower subscriptions and gift arrangements."),
        ],
        "queries": ["florist flower shop bouquet", "fresh flowers floral arrangement", "flower shop wedding florals"],
        "included": ["Online order & delivery", "Wedding consultation form", "Seasonal arrangement gallery", "Google Maps & hours", "Mobile-friendly site", "Custom order inquiry"],
        "reviews": [
            ("Sarah K.",   5, "Ordered a last-minute bouquet and they delivered within 2 hours. Absolutely stunning arrangement. My mom was in tears."),
            ("Michael B.", 5, "They did the florals for our wedding and every single piece was breathtaking. Our guests couldn't stop complimenting them."),
            ("Emma R.",    4, "I get a weekly subscription and the flowers are always fresh and beautifully arranged. Worth every dollar."),
        ],
    },
    "tattoo parlor": {
        "accent": "#DC7A7A", "dark": "#A84040", "bg": "#100606",
        "tag": "Tattoo Studio", "tagline": "Custom Tattoos by Artists Who Care",
        "services": [
            ("🎨", "Custom Tattoo Design", "Original artwork created specifically for you — no flash, no cookie cutters."),
            ("🔄", "Cover-Up Tattoos",     "Expert cover-up work to transform tattoos you've outgrown into something new."),
            ("💎", "Fine Line & Minimalist","Delicate linework, micro-tattoos, and minimalist designs by specialized artists."),
            ("🌈", "Color & Realism",       "Full-color portraits, nature scenes, and photorealistic tattoos."),
        ],
        "queries": ["tattoo studio artist ink", "custom tattoo design studio", "tattoo art studio professional"],
        "included": ["Artist portfolios & styles", "Booking & deposit form", "Aftercare instructions page", "Google Maps & studio hours", "Mobile-friendly site", "Consultation request form"],
        "reviews": [
            ("Jake W.",    5, "My artist took my rough idea and turned it into something I'll be proud of forever. The attention to detail is insane."),
            ("Priya S.",   5, "Got a full sleeve done here over multiple sessions. The work is stunning and the studio is immaculately clean."),
            ("Aaron M.",   4, "Very professional shop. Great artists, clean environment, and they take their time to get it right."),
        ],
    },
    "gym": {
        "accent": "#E8A040", "dark": "#B07020", "bg": "#0e0900",
        "tag": "Fitness", "tagline": "Train Harder. Recover Better. Live Stronger.",
        "services": [
            ("🏋️", "Open Gym Access",      "State-of-the-art equipment for strength training, cardio, and functional fitness."),
            ("👥", "Group Fitness Classes", "HIIT, yoga, spin, kickboxing, and more — over 20 classes per week."),
            ("🎯", "Personal Training",     "One-on-one sessions with certified trainers who build programs around your goals."),
            ("🥤", "Nutrition Coaching",    "Personalized meal planning and nutrition guidance to maximize your results."),
        ],
        "queries": ["gym fitness workout equipment", "fitness center gym training", "personal training gym workout"],
        "included": ["Class schedule & booking", "Membership packages page", "Trainer profiles", "Google Maps & hours", "Mobile-friendly site", "Free trial sign-up form"],
        "reviews": [
            ("Chris P.",   5, "Best gym in the area. The equipment is always clean and maintained, the classes are challenging, and the trainers actually care."),
            ("Nina J.",    5, "I've been a member for 8 months and lost 30 lbs. The community here is incredibly supportive and motivating."),
            ("Derek L.",   4, "Great facility with a wide variety of equipment and classes. Never feels overcrowded, even during peak hours."),
        ],
    },
    "photographer": {
        "accent": "#C8B090", "dark": "#887040", "bg": "#0c0a08",
        "tag": "Photography", "tagline": "Professional Photography for Life's Moments",
        "services": [
            ("👤", "Portraits & Headshots", "Professional headshots, family portraits, and senior photos with quick turnaround."),
            ("💒", "Weddings & Events",      "Full wedding day coverage, engagement sessions, and event photography packages."),
            ("🏠", "Real Estate Photography","HDR listing photos, drone shots, and virtual tours that sell properties faster."),
            ("📦", "Brand & Product",        "E-commerce product shots, brand lifestyle photography, and social media content."),
        ],
        "queries": ["professional photographer studio portrait", "wedding photography couple", "photography studio camera"],
        "included": ["Portfolio gallery by category", "Package pricing page", "Online booking & inquiry", "Google Maps & studio info", "Mobile-friendly site", "Client questionnaire form"],
        "reviews": [
            ("Olivia R.",  5, "Our wedding photos are absolutely stunning. Every important moment was captured and the editing is flawless."),
            ("Mark H.",    5, "Used them for my business headshots and the quality blew me away. Fast turnaround and very professional."),
            ("Jessica T.", 4, "Beautiful family portraits. The photographer made my kids feel completely comfortable and the photos are priceless."),
        ],
    },
    "pet grooming": {
        "accent": "#80C880", "dark": "#408840", "bg": "#060e06",
        "tag": "Pet Grooming", "tagline": "Your Pet Deserves to Look & Feel Their Best",
        "services": [
            ("🐕", "Full Groom Package",   "Bath, blow-dry, haircut, nail trim, ear cleaning, and bandana for your pup."),
            ("🛁", "Bath & Brush-Out",     "Thorough bath with premium shampoo, blow-dry, and full brush-out."),
            ("✂️", "Breed-Specific Cuts",  "Expert scissor work following breed standards for all dog breeds."),
            ("🐱", "Cat Grooming",         "Gentle cat grooming services including bathing, dematting, and lion cuts."),
        ],
        "queries": ["pet grooming dog groomer salon", "dog grooming professional salon", "pet salon grooming puppy"],
        "included": ["Online appointment booking", "Service menu & pricing", "Pet photo gallery", "Google Maps & hours", "Mobile-friendly site", "New pet intake form"],
        "reviews": [
            ("Sophie M.",  5, "My golden retriever looks like he just came from a photoshoot every time he leaves here. Incredible groomers!"),
            ("Tom A.",     5, "They're so gentle with my anxious dog. He actually gets excited when we arrive, which says everything."),
            ("Rachel K.",  4, "Consistent, professional, and they really listen to how you want your dog to look. Highly recommend."),
        ],
    },
    "beauty salon": {
        "accent": "#E8A4C8", "dark": "#8B3A6B", "bg": "#0d0508",
        "tag": "Beauty & Style", "tagline": "Your Full-Service Beauty Destination",
        "services": [
            ("💄", "Hair Styling & Color",   "Cuts, blowouts, highlights, keratin, and custom color by experienced stylists."),
            ("💅", "Nails & Manicures",      "Gel, acrylic, and natural nail care plus pedicures in a relaxing environment."),
            ("👁️", "Lashes & Brows",         "Lash extensions, lifts, microblading, tinting, and brow shaping by experts."),
            ("✨", "Skin & Waxing",          "Facials, waxing, threading, and skin treatments for a flawless finish."),
        ],
        "queries": ["beauty salon interior modern", "hair salon styling woman", "beauty parlor professional glam"],
        "included": ["Online appointment booking", "Full service & pricing menu", "Before & after gallery", "Google Maps & hours", "Mobile-friendly site", "Contact & booking form"],
        "reviews": [
            ("Jasmine T.", 5, "Best salon in the area — they do everything here. Hair, nails, lashes. I never have to go anywhere else."),
            ("Carmen R.",  5, "My hair has never looked so good. The colorist is absolutely amazing and the price is very reasonable."),
            ("Aaliyah M.", 4, "Great experience every single time. The staff is professional, friendly, and they always deliver."),
        ],
    },
    "landscaping": {
        "accent": "#7DC67E", "dark": "#2E7D32", "bg": "#040a04",
        "tag": "Lawn & Landscaping", "tagline": "Professional Landscaping & Lawn Care Services",
        "services": [
            ("🌿", "Lawn Mowing & Edging",   "Weekly and bi-weekly mowing, edging, and cleanup to keep your property pristine."),
            ("🌳", "Landscaping & Design",   "Custom landscape design, planting, mulching, and hardscape installation."),
            ("🍂", "Seasonal Cleanup",        "Spring and fall cleanups, leaf removal, and bed maintenance all season long."),
            ("❄️", "Snow Removal",            "Reliable commercial and residential snow plowing, salting, and ice management."),
        ],
        "queries": ["landscaping lawn green professional", "garden landscaping design", "lawn mowing service yard"],
        "included": ["Free estimate request form", "Service packages & pricing", "Before & after gallery", "Google Maps & coverage area", "Mobile-friendly site", "Seasonal service calendar"],
        "reviews": [
            ("Robert M.",  5, "They transformed my backyard completely. Professional, on time, and the results are better than I imagined."),
            ("Linda C.",   5, "Reliable every single week. My lawn always looks perfect and the crew is respectful of the property."),
            ("David P.",   4, "Great communication and fair pricing. They showed up on time and did exactly what was promised."),
        ],
    },
    "lawn care": {
        "accent": "#7DC67E", "dark": "#2E7D32", "bg": "#040a04",
        "tag": "Lawn & Landscaping", "tagline": "Professional Lawn Care & Outdoor Services",
        "services": [
            ("🌿", "Lawn Mowing & Edging",   "Weekly and bi-weekly mowing, edging, and cleanup to keep your property pristine."),
            ("🌳", "Landscaping & Design",   "Custom landscape design, planting, mulching, and hardscape installation."),
            ("🍂", "Seasonal Cleanup",        "Spring and fall cleanups, leaf removal, and bed maintenance all season long."),
            ("❄️", "Snow Removal",            "Reliable commercial and residential snow plowing, salting, and ice management."),
        ],
        "queries": ["lawn mowing service yard", "landscaping lawn green professional", "garden landscaping design"],
        "included": ["Free estimate request form", "Service packages & pricing", "Before & after gallery", "Google Maps & coverage area", "Mobile-friendly site", "Seasonal service calendar"],
        "reviews": [
            ("Robert M.",  5, "They transformed my backyard completely. Professional, on time, and the results are better than I imagined."),
            ("Linda C.",   5, "Reliable every single week. My lawn always looks perfect and the crew is respectful of the property."),
            ("David P.",   4, "Great communication and fair pricing. They showed up on time and did exactly what was promised."),
        ],
    },
    "mechanic": {
        "accent": "#5BA3D9", "dark": "#1A4A7A", "bg": "#04080d",
        "tag": "Auto Repair", "tagline": "Trusted Mechanics You Can Count On",
        "services": [
            ("🔧", "Engine Diagnostics",     "Computer diagnostics and expert troubleshooting for check engine lights and more."),
            ("🛢️", "Oil Change & Fluids",    "Conventional, synthetic, and high-mileage oil changes with full fluid inspection."),
            ("🚗", "Brake Service",           "Brake pad replacement, rotor resurfacing, and full brake system inspections."),
            ("⚙️", "Transmission & Drivetrain","Transmission service, clutch repair, and drivetrain maintenance by certified techs."),
        ],
        "queries": ["auto mechanic garage car repair", "mechanic working on vehicle engine", "car repair shop professional"],
        "included": ["Online appointment booking", "Service menu & pricing", "ASE-certified team profiles", "Google Maps & hours", "Mobile-friendly site", "Free estimate request form"],
        "reviews": [
            ("Mike T.",    5, "Finally found an honest mechanic. They fixed my car fast, explained everything clearly, and didn't overcharge."),
            ("Sandra L.",  5, "Brought my car in for a noise no one else could figure out. They diagnosed it in 20 minutes and fixed it the same day."),
            ("James R.",   4, "Great service and fair prices. They always call before doing anything extra and that's huge for me."),
        ],
    },
    "tire shop": {
        "accent": "#F5A623", "dark": "#8B5E00", "bg": "#0a0700",
        "tag": "Tires & Wheels", "tagline": "Expert Tire Sales, Installation & Service",
        "services": [
            ("🔄", "Tire Installation",      "New tire mounting and installation for all makes and models, in and out fast."),
            ("⚖️", "Wheel Balancing",        "Precision wheel balancing to eliminate vibration and extend tire life."),
            ("🩹", "Flat Repair",             "Quick, reliable flat tire repair and plug service — same-day turnaround."),
            ("📐", "Wheel Alignment",         "Computer-aided alignment to improve handling, fuel economy, and tire wear."),
        ],
        "queries": ["tire shop garage auto wheels", "car tire change service professional", "tire installation wheel auto shop"],
        "included": ["Online appointment booking", "Tire brands & pricing page", "Service specials & coupons", "Google Maps & hours", "Mobile-friendly site", "Free alignment check form"],
        "reviews": [
            ("Carlos M.",  5, "In and out in 30 minutes for four new tires. The price was right and the service was excellent."),
            ("Tanya W.",   5, "Got a flat on a Friday afternoon and they fit me in immediately. Lifesavers — I'll only come here now."),
            ("Greg B.",    4, "Great prices, friendly staff, and no upselling. Exactly the kind of shop you want to find in your neighborhood."),
        ],
    },
    "lash studio": {
        "accent": "#D4A8C8", "dark": "#7A3A6A", "bg": "#0d0609",
        "tag": "Lash & Brow Studio", "tagline": "Professional Lash Extensions & Brow Services",
        "services": [
            ("👁️", "Lash Extensions",        "Classic, hybrid, and volume lash sets applied by certified lash artists."),
            ("✨", "Lash Lifts & Tints",      "Lift your natural lashes and add tint for a mascara-free, wide-eyed look."),
            ("🎨", "Brow Shaping & Design",   "Microblading, lamination, tinting, and precision waxing for perfect brows."),
            ("💆", "Lash Removal & Fills",    "Safe lash removal and 2-3 week fill appointments to keep your set looking fresh."),
        ],
        "queries": ["lash extensions beauty studio", "eyelash salon professional", "lash artist beauty studio"],
        "included": ["Online appointment booking", "Service menu & pricing", "Before & after gallery", "Google Maps & hours", "Mobile-friendly site", "New client intake form"],
        "reviews": [
            ("Brianna K.", 5, "My lashes have never looked this good. The artist is so precise and they last a full 3 weeks."),
            ("Nadia R.",   5, "Absolute perfection every time. I get compliments on my lashes everywhere I go."),
            ("Tamara L.",  4, "Great experience, very professional, and the brow lamination completely changed my face."),
        ],
    },
    "pizza": {
        "accent": "#E8724A", "dark": "#8B3010", "bg": "#0d0604",
        "tag": "Pizza Restaurant", "tagline": "Fresh Dough. Real Ingredients. Every Slice.",
        "services": [
            ("🍕", "Classic & Specialty Pies", "From NY-style thin crust to loaded specialty pies, baked fresh to order."),
            ("🥗", "Salads & Starters",        "Fresh salads, garlic knots, mozzarella sticks, and wings to start the meal right."),
            ("🥡", "Delivery & Takeout",        "Fast delivery and easy online ordering — hot pizza at your door in under 45 minutes."),
            ("🎉", "Catering & Parties",        "Pizza party trays, catering packages, and event orders for any size group."),
        ],
        "queries": ["pizza restaurant slice fresh", "pizza oven wood fired artisan", "pizza shop interior restaurant"],
        "included": ["Online ordering & menu", "Delivery zone map", "Special deals & coupons", "Google Maps & hours", "Mobile-friendly site", "Catering inquiry form"],
        "reviews": [
            ("Joey M.",    5, "Best pizza in the neighborhood, no question. The sauce, the crust, the cheese — all perfect."),
            ("Tanya G.",   5, "We order from here every Friday. Always hot, always on time, always delicious."),
            ("Kevin P.",   4, "Solid slices and fast delivery. The garlic knots alone are worth the trip."),
        ],
    },
    "vet": {
        "accent": "#5BB8A8", "dark": "#1A6A5A", "bg": "#040d0b",
        "tag": "Veterinary Care", "tagline": "Compassionate Care for Your Pets",
        "services": [
            ("🐾", "Wellness Exams",          "Annual and bi-annual checkups, vaccinations, and preventive care for pets of all ages."),
            ("💉", "Vaccinations & Boosters", "Core and lifestyle vaccines administered by licensed veterinarians on schedule."),
            ("🔬", "Diagnostics & Lab Work",  "In-house bloodwork, urinalysis, X-rays, and ultrasound for fast, accurate results."),
            ("🏥", "Surgery & Dental Care",   "Routine and emergency surgical procedures plus professional dental cleanings."),
        ],
        "queries": ["veterinary clinic pet care", "vet office animal hospital", "veterinarian dog cat clinic"],
        "included": ["Online appointment booking", "Services & pricing page", "Meet our vets profiles", "Google Maps & hours", "Mobile-friendly site", "New patient intake form"],
        "reviews": [
            ("Chloe M.",   5, "They treat our dog like he's their own. The vets are so knowledgeable and the staff genuinely cares."),
            ("Paul T.",    5, "Excellent vet, fair prices, and they always get us in quickly when there's an emergency."),
            ("Amber S.",   4, "Kind, patient staff and very thorough. My anxious cat actually tolerates visits here."),
        ],
    },
    "car wash": {
        "accent": "#4AB8E8", "dark": "#1A6A9A", "bg": "#04090d",
        "tag": "Car Wash & Detailing", "tagline": "Professional Auto Detailing & Car Wash",
        "services": [
            ("🚿", "Full-Service Car Wash",   "Exterior wash, hand dry, windows, tires, and interior vacuum — all in one visit."),
            ("✨", "Interior Detailing",       "Deep interior clean including seats, carpets, dashboard, and odor elimination."),
            ("🪟", "Exterior Detail & Wax",    "Clay bar treatment, hand wax, polish, and paint protection for a showroom shine."),
            ("🚗", "Express Wash",             "Quick exterior wash and dry for when you're in a hurry — in and out in minutes."),
        ],
        "queries": ["car wash auto detailing professional", "car detailing service exterior", "auto car wash clean vehicle"],
        "included": ["Service packages & pricing", "Online booking or drive-in info", "Before & after gallery", "Google Maps & hours", "Mobile-friendly site", "Loyalty & membership info"],
        "reviews": [
            ("Steve L.",   5, "My car looks brand new after every visit. The detailing crew is incredibly thorough."),
            ("Monica J.",  5, "Best car wash in the area. Fast, affordable, and my car is spotless every single time."),
            ("Ray C.",     4, "Great full detail for the price. They got stains out I thought were permanent."),
        ],
    },
    "fitness": {
        "accent": "#E85A4F", "dark": "#8B1A10", "bg": "#0d0404",
        "tag": "Fitness Center", "tagline": "Train Hard. Get Results. Feel Amazing.",
        "services": [
            ("🏋️", "Strength Training",       "Full free weight area, machines, and barbells for all fitness levels."),
            ("🏃", "Cardio & Conditioning",   "Treadmills, bikes, rowers, and open floor space for conditioning work."),
            ("🧘", "Group Fitness Classes",    "Yoga, HIIT, cycling, Zumba, and more — included with all memberships."),
            ("👥", "Personal Training",        "One-on-one coaching with certified trainers to hit your specific goals faster."),
        ],
        "queries": ["fitness center gym workout", "gym exercise equipment weights", "fitness studio training workout"],
        "included": ["Class schedule & booking", "Membership packages page", "Trainer profiles", "Google Maps & hours", "Mobile-friendly site", "Free trial sign-up form"],
        "reviews": [
            ("Darius M.",  5, "This gym has everything I need and the trainers actually check in on you. Worth every penny."),
            ("Kira T.",    5, "Clean equipment, great classes, and a really positive atmosphere. I've hit my goals faster than ever."),
            ("Leon B.",    4, "Solid gym with a great community feel. The staff knows your name and that makes a difference."),
        ],
    },
    "personal trainer": {
        "accent": "#E85A4F", "dark": "#8B1A10", "bg": "#0d0404",
        "tag": "Personal Training", "tagline": "Your Goals. Your Coach. Your Results.",
        "services": [
            ("🎯", "1-on-1 Personal Training", "Customized workout programs designed for your body, schedule, and specific goals."),
            ("📋", "Nutrition Coaching",        "Personalized meal planning and nutrition guidance to maximize your results."),
            ("👥", "Small Group Training",      "Cost-effective small group sessions with the energy of a team environment."),
            ("🏠", "In-Home & Virtual Training","Flexible sessions at your home or live online — train anywhere, anytime."),
        ],
        "queries": ["personal trainer fitness coaching", "personal training workout session", "fitness trainer gym workout"],
        "included": ["Training package pricing", "Trainer bio & certifications", "Transformation gallery", "Online booking & scheduling", "Mobile-friendly site", "Free consultation form"],
        "reviews": [
            ("Jasmine W.", 5, "Lost 30 pounds in 4 months and I've kept it off. Best investment I've made in myself."),
            ("Marcus G.",  5, "My trainer pushes me in the best way. I've made more progress in 3 months than years on my own."),
            ("Serena L.",  4, "The nutrition plan alone was worth it. I finally understand how to eat for my body type."),
        ],
    },
    "videographer": {
        "accent": "#9B6FE8", "dark": "#4A1FA8", "bg": "#07050e",
        "tag": "Video Production", "tagline": "Cinematic Video That Tells Your Story",
        "services": [
            ("🎬", "Event Videography",      "Full coverage of weddings, parties, corporate events, and milestones in stunning HD."),
            ("📺", "Commercial & Brand Video","Professional brand films, product videos, and social media content that converts."),
            ("🚁", "Drone Footage",           "FAA-certified aerial drone coverage for real estate, events, and cinematic B-roll."),
            ("💍", "Wedding Films",           "Cinematic same-day edits, highlight reels, and full-length wedding films."),
        ],
        "queries": ["videographer filming camera professional", "video production studio equipment", "filmmaker camera cinematic shoot"],
        "included": ["Video portfolio & reel page", "Package pricing & add-ons", "Online booking & inquiry", "Google Maps & studio info", "Mobile-friendly site", "Custom quote request form"],
        "reviews": [
            ("Brianna J.", 5, "Our wedding video made us cry the first time we watched it. Every detail was captured perfectly."),
            ("Marcus A.",  5, "They produced our company promo video and it completely elevated our brand. Incredibly professional team."),
            ("Destiny C.", 4, "Fast turnaround, creative direction, and they really listen to your vision. Will be using them again."),
        ],
    },
    "pet store": {
        "accent": "#5BB8E8", "dark": "#1A6A9A", "bg": "#04080d",
        "tag": "Pet Store", "tagline": "Everything Your Pet Needs Under One Roof",
        "services": [
            ("🐾", "Pet Food & Nutrition",    "Premium dry, wet, raw, and specialty diets for dogs, cats, birds, and more."),
            ("🧸", "Toys & Accessories",       "Leashes, collars, beds, crates, and hundreds of toys for every type of pet."),
            ("🐠", "Aquarium & Small Animals", "Fish, tanks, live plants, small animals, and all the supplies to care for them."),
            ("💊", "Health & Wellness",        "Flea & tick prevention, vitamins, dental care, and vet-recommended products."),
        ],
        "queries": ["pet store interior animals supplies", "pet shop aquarium fish supplies", "pet store dog cat supplies"],
        "included": ["Product categories & pricing", "In-store services page", "Google Maps & hours", "Mobile-friendly site", "Loyalty program info", "Contact & inquiry form"],
        "reviews": [
            ("Priya S.",   5, "This is our go-to pet store. They carry everything and the staff always knows exactly what our dog needs."),
            ("Hector M.",  5, "The fish selection here is incredible. The staff is knowledgeable and the tanks are always healthy."),
            ("Diane T.",   4, "Great prices and a huge selection. I love that they carry specialty food brands I can't find anywhere else."),
        ],
    },
    "yoga studio": {
        "accent": "#B89FD8", "dark": "#5A3A8A", "bg": "#080510",
        "tag": "Yoga & Wellness", "tagline": "Find Your Balance. Move With Intention.",
        "services": [
            ("🧘", "Yoga Classes",             "All levels welcome — Hatha, Vinyasa, Yin, restorative, and beginner flows daily."),
            ("🌬️", "Breathwork & Meditation",  "Guided meditation, pranayama, and mindfulness sessions for mental clarity and calm."),
            ("🌟", "Private Sessions",          "One-on-one yoga instruction tailored to your body, goals, and experience level."),
            ("🎓", "Workshops & Retreats",      "Weekend workshops, seasonal intensives, and local retreat experiences."),
        ],
        "queries": ["yoga studio class peaceful interior", "yoga meditation group class", "yoga studio serene wellness"],
        "included": ["Class schedule & online booking", "Membership packages & drop-ins", "Instructor profiles", "Google Maps & hours", "Mobile-friendly site", "Free first class form"],
        "reviews": [
            ("Naomi P.",   5, "This studio changed my life. The instructors are world-class and the energy in every class is incredible."),
            ("Claire H.",  5, "Finally a studio where I feel welcome as a beginner. No judgment, just growth."),
            ("Derek W.",   4, "I've been practicing for 10 years and this is still the best studio I've found. Great teachers, great community."),
        ],
    },
    "ice cream": {
        "accent": "#F5B8D0", "dark": "#C85A8A", "bg": "#0d0608",
        "tag": "Ice Cream & Desserts", "tagline": "Every Scoop Is a Good Mood",
        "services": [
            ("🍦", "Ice Cream & Gelato",       "Rotating flavors of handcrafted ice cream, gelato, and sorbet made fresh daily."),
            ("🥤", "Milkshakes & Floats",       "Thick, creamy milkshakes and root beer floats made with premium ice cream."),
            ("🍨", "Sundaes & Splits",          "Build your own sundae with toppings, hot fudge, whipped cream, and cherries."),
            ("🎂", "Ice Cream Cakes & Catering","Custom ice cream cakes and party catering for birthdays and special events."),
        ],
        "queries": ["ice cream shop interior colorful", "ice cream scoops dessert shop", "ice cream parlor sweet desserts"],
        "included": ["Rotating flavor menu", "Online ordering & pickup", "Party & catering packages", "Google Maps & hours", "Mobile-friendly site", "Birthday special signup"],
        "reviews": [
            ("Lily C.",    5, "Best ice cream in the neighborhood — the flavors are so creative and the portions are generous."),
            ("Tyler M.",   5, "My kids beg to come here every week. The sundaes are incredible and the staff is always friendly."),
            ("Rosa D.",    4, "The mango sorbet is absolutely perfect. Clean, bright, and not too sweet. I'm addicted."),
        ],
    },
    "electrician": {
        "accent": "#F5D020", "dark": "#8B7A00", "bg": "#0a0900",
        "tag": "Electrical Services", "tagline": "Licensed Electricians You Can Trust",
        "services": [
            ("⚡", "Residential Wiring",       "New construction wiring, rewiring, and electrical upgrades for your home."),
            ("🔌", "Outlets & Panel Upgrades", "Outlet installation, GFCI upgrades, panel replacements, and load balancing."),
            ("💡", "Lighting Installation",    "Interior and exterior lighting, recessed lights, ceiling fans, and smart home."),
            ("🚨", "Emergency Service",         "24/7 emergency electrical service — no call too urgent, licensed and insured."),
        ],
        "queries": ["electrician electrical work professional", "electrical contractor wiring panel", "licensed electrician work residential"],
        "included": ["Free estimate request form", "Services & pricing page", "Licensed & insured badge", "Google Maps & service area", "Mobile-friendly site", "Emergency contact line"],
        "reviews": [
            ("Frank R.",   5, "Responded to my electrical emergency same day. Fixed the problem fast and the price was fair."),
            ("Gina M.",    5, "We had the whole house rewired and they were clean, professional, and on budget the whole time."),
            ("Steve K.",   4, "Solid electricians. They explained everything clearly and I never felt like I was being upsold."),
        ],
    },
    "dry cleaner": {
        "accent": "#88C8E8", "dark": "#3A7EA8", "bg": "#05090d",
        "tag": "Dry Cleaning & Alterations", "tagline": "Your Clothes, Cleaned & Cared For",
        "services": [
            ("👔", "Dry Cleaning",             "Expert dry cleaning for suits, dresses, coats, and delicate fabrics done right."),
            ("✂️", "Alterations & Tailoring",  "Hemming, resizing, repairs, and custom tailoring by our experienced seamstresses."),
            ("👗", "Wedding Gown Services",     "Bridal gown cleaning, preservation, and restoration handled with extra care."),
            ("🚗", "Pickup & Delivery",         "Free pickup and delivery service — we come to you and bring your clothes back fresh."),
        ],
        "queries": ["dry cleaning laundry store professional", "dry cleaner interior clothing service", "laundry cleaning professional service"],
        "included": ["Service menu & pricing", "Pickup & delivery scheduling", "Turnaround time guarantee", "Google Maps & hours", "Mobile-friendly site", "Order tracking info"],
        "reviews": [
            ("Helen C.",   5, "My wedding dress looked absolutely perfect after their cleaning. I was so worried and they exceeded every expectation."),
            ("Paul N.",    5, "Best dry cleaner in the area. My suits always come back perfectly pressed and ready to wear."),
            ("Maria S.",   4, "The alteration on my dress was flawless. Fast turnaround and very reasonable prices."),
        ],
    },
    "diner": {
        "accent": "#E84848", "dark": "#8B1010", "bg": "#0d0404",
        "tag": "American Diner", "tagline": "Classic Food. Honest Prices. Good People.",
        "services": [
            ("🍳", "Breakfast All Day",         "Eggs, pancakes, waffles, omelets, and all your breakfast favorites — any time."),
            ("🍔", "Burgers & Sandwiches",      "Hand-pressed burgers, cheesesteaks, clubs, and classic deli sandwiches."),
            ("🍽️", "Daily Blue Plate Specials", "Rotating home-cooked specials every day — real food at real prices."),
            ("☕", "Coffee & Desserts",          "Hot coffee, milkshakes, homemade pie, and classic diner desserts."),
        ],
        "queries": ["american diner interior classic retro", "diner breakfast food plate", "classic diner counter restaurant"],
        "included": ["Full menu with photos", "Daily specials board", "Catering & large orders", "Google Maps & hours", "Mobile-friendly site", "Online ordering option"],
        "reviews": [
            ("Bill T.",    5, "This diner is the real deal. Huge portions, fair prices, and the eggs are cooked exactly how you order them."),
            ("Susan M.",   5, "My family has been coming here for 20 years. It never changes and that's exactly why we love it."),
            ("Joe R.",     4, "Best breakfast in the area, hands down. The coffee is always hot and the staff remembers your order."),
        ],
    },
    "dog walker": {
        "accent": "#80D880", "dark": "#308830", "bg": "#050d05",
        "tag": "Dog Walking & Pet Care", "tagline": "Trusted, Loving Care While You're Away",
        "services": [
            ("🦮", "Dog Walking",               "Daily solo and group walks with GPS tracking and real-time photo updates."),
            ("🏠", "Pet Sitting & Drop-Ins",    "In-home overnight stays or drop-in visits so your pet stays comfortable at home."),
            ("🐾", "Puppy Care",                "Extra attention and potty breaks for puppies under one year old."),
            ("🚗", "Doggy Daycare Transport",   "Safe pickup and drop-off for doggy daycare so your pet's day runs smoothly."),
        ],
        "queries": ["dog walker walking dogs outdoor", "pet sitter dog walking service", "dog walker person dogs leash park"],
        "included": ["Online booking & scheduling", "Service packages & pricing", "GPS walk reports & photos", "Google Maps & service area", "Mobile-friendly site", "New client intake form"],
        "reviews": [
            ("Ashley M.",  5, "Our dog absolutely loves her walker. We get photo updates every walk and she comes home so happy."),
            ("Chris P.",   5, "Reliable, trustworthy, and my dog goes crazy with excitement every time they arrive. 10/10."),
            ("Rachel G.",  4, "Great communication and you can tell they genuinely love animals. Worth every penny for the peace of mind."),
        ],
    },
}

DEFAULT_CAT = {
    "accent": "#C9A96E", "dark": "#8B6E3E", "bg": "#0d0d0d",
    "tag": "Local Business", "tagline": "Serving Philadelphia With Quality & Care",
    "services": [
        ("⭐", "Quality Service",        "Consistent, professional service that exceeds expectations every time."),
        ("🤝", "Easy Online Booking",    "Book appointments, request quotes, or ask questions right from our website."),
        ("📍", "Locally Owned",          "Proudly serving our Philadelphia community with the care of a local business."),
        ("✅", "Satisfaction Guaranteed","If you're not happy, we make it right. That's our promise to every customer."),
    ],
    "queries": ["local business service professional", "small business storefront professional"],
    "included": ["Services & pricing page", "Online booking or quote form", "Photo gallery", "Google Maps & hours", "Mobile-friendly design", "Contact form"],
    "reviews": [
        ("Michael T.", 5, "Outstanding service from start to finish. Professional, friendly, and truly excellent at what they do."),
        ("Laura B.",   5, "I've been a loyal customer for years and the quality never drops. They've earned every star."),
        ("David R.",   4, "Reliable, reasonably priced, and the team is always a pleasure to work with. Highly recommend."),
    ],
}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _cat(category: str) -> dict:
    cat = (category or "").lower().strip()
    for k, t in CATS.items():
        if k in cat or cat in k:
            return t
    return DEFAULT_CAT


def _picsum_url(seed: str, w: int, h: int, idx: int = 0) -> str:
    """Lorem Picsum — reliable, always works, beautiful photography."""
    safe = re.sub(r"[^a-z0-9]", "", seed.lower()) + str(idx)
    return f"https://picsum.photos/seed/{safe}/{w}/{h}"


def _upload_video(mp4_data: bytes, fname: str) -> str:
    """Upload MP4 bytes to Supabase. Returns public URL or ''."""
    pub_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{fname}"
    up_url  = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{fname}"
    up_req  = urllib.request.Request(
        up_url, data=mp4_data, method="POST",
        headers={"Authorization": f"Bearer {SERVICE_KEY}", "Content-Type": "video/mp4", "x-upsert": "true"})
    try:
        urllib.request.urlopen(up_req, timeout=60)
        print(f"  Video   : {pub_url}")
        return pub_url
    except Exception:
        return ""


def _pexels_video_and_upload(query: str, biz_slug: str) -> str:
    """Try Pixabay first (free, instant key), then Pexels video (needs approval). Returns URL or ''."""
    import urllib.parse as _up
    fname   = f"{biz_slug}-hero.mp4"
    pub_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{fname}"
    try:
        urllib.request.urlopen(pub_url, timeout=4)
        return pub_url  # already cached
    except Exception:
        pass

    # --- Pixabay Video (free, instant API key at pixabay.com/api/docs/) ---
    if PIXABAY_KEY:
        q   = _up.quote(query)
        url = f"https://pixabay.com/api/videos/?key={PIXABAY_KEY}&q={q}&video_type=film&orientation=horizontal&per_page=10&safesearch=true"
        try:
            data  = json.loads(urllib.request.urlopen(url, timeout=10).read())
            hits  = data.get("hits", [])
            for hit in hits[:5]:
                mp4_url = hit.get("videos", {}).get("medium", {}).get("url", "")
                if not mp4_url:
                    mp4_url = hit.get("videos", {}).get("small", {}).get("url", "")
                if not mp4_url:
                    continue
                try:
                    dl_req   = urllib.request.Request(mp4_url, headers={
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                        "Referer":    "https://pixabay.com/",
                    })
                    mp4_data = urllib.request.urlopen(dl_req, timeout=90).read()
                except Exception:
                    continue
                if len(mp4_data) > 48_000_000:
                    continue
                result = _upload_video(mp4_data, fname)
                if result:
                    return result
        except Exception:
            pass

    # --- Pexels Video (same key as photos, but needs video API approval) ---
    if PEXELS_KEY:
        q   = _up.quote(query)
        req = urllib.request.Request(
            f"https://api.pexels.com/videos/search?query={q}&per_page=10&orientation=landscape&size=medium",
            headers={"Authorization": PEXELS_KEY, "User-Agent": _BROWSER_UA})
        try:
            data   = json.loads(urllib.request.urlopen(req, timeout=10).read())
            videos = data.get("videos", [])
            for video in videos[:5]:
                files = [f for f in video.get("video_files", []) if f.get("file_type") == "video/mp4"]
                if not files:
                    continue
                best = min(files, key=lambda f: abs(f.get("width", 0) - 960))
                try:
                    mp4_data = urllib.request.urlopen(best["link"], timeout=90).read()
                except Exception:
                    continue
                if len(mp4_data) > 48_000_000:
                    continue
                result = _upload_video(mp4_data, fname)
                if result:
                    return result
        except Exception:
            pass

    return ""


_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def _pexels_and_upload(query: str, idx: int, biz_slug: str) -> str:
    """Download one Pexels photo and upload to Supabase. Returns public URL or ''."""
    if not PEXELS_KEY:
        return ""
    fname   = f"{biz_slug}-img{idx}.jpg"
    pub_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{fname}"
    # Return early if already uploaded
    try:
        urllib.request.urlopen(pub_url, timeout=4)
        return pub_url
    except Exception:
        pass
    # Fetch from Pexels — must use browser UA or Pexels returns 403
    q   = urllib.parse.quote(query)
    req = urllib.request.Request(
        f"https://api.pexels.com/v1/search?query={q}&per_page=8&orientation=landscape",
        headers={
            "Authorization": PEXELS_KEY,
            "User-Agent":    _BROWSER_UA,
        })
    try:
        data     = json.loads(urllib.request.urlopen(req, timeout=10).read())
        photos   = data.get("photos", [])
        if not photos:
            return ""
        img_url  = photos[idx % len(photos)]["src"]["large2x"]
        img_req  = urllib.request.Request(img_url, headers={"User-Agent": _BROWSER_UA})
        img_data = urllib.request.urlopen(img_req, timeout=30).read()
    except Exception:
        return ""
    # Upload to Supabase (try PUT first so x-upsert works cleanly)
    up_url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{fname}"
    for method in ("PUT", "POST"):
        up_req = urllib.request.Request(
            up_url, data=img_data, method=method,
            headers={
                "Authorization": f"Bearer {SERVICE_KEY}",
                "Content-Type":  "image/jpeg",
                "x-upsert":      "true",
            })
        try:
            urllib.request.urlopen(up_req, timeout=30)
            return pub_url
        except urllib.error.HTTPError as e:
            if e.code in (400, 409) and method == "POST":
                continue
            return ""
        except Exception:
            return ""
    return ""


# Need urllib.parse for quote
import urllib.parse


_NAME_KEYWORD_QUERIES = {
    "book":       ["bookstore interior shelves", "bookstore cafe cozy", "books reading coffee shop", "library books shelves"],
    "seafood":    ["seafood restaurant fresh fish", "seafood platter ocean", "fish restaurant dining", "shrimp crab seafood dish"],
    "chicken":    ["fried chicken restaurant", "chicken wings crispy", "chicken sandwich restaurant", "rotisserie chicken"],
    "pizza":      ["pizza restaurant slice", "pizza oven wood fired", "pizza dough toppings", "italian pizza restaurant"],
    "sushi":      ["sushi restaurant rolls", "japanese sushi platter", "sushi chef fish", "sushi bar restaurant"],
    "bbq":        ["bbq smokehouse ribs", "barbecue brisket smoked", "bbq restaurant grill", "smoked meat platter"],
    "park":       ["park outdoor green space", "park trees nature", "outdoor recreation park", "green park landscape"],
    "gym":        ["gym weights fitness", "workout gym equipment", "fitness center exercise", "gym training strength"],
    "salon":      ["hair salon styling", "hair salon interior", "salon chair styling", "hair color highlights"],
    "beauty":     ["beauty salon interior modern", "hair salon styling woman", "beauty parlor professional glam", "makeup beauty salon"],
    "landscap":   ["landscaping lawn green professional", "garden landscaping design", "lawn mowing service yard", "landscape design outdoor"],
    "lawn":       ["lawn mowing service yard", "landscaping lawn green professional", "garden landscaping design", "grass cutting lawn care"],
    "mechanic":   ["auto mechanic garage car repair", "mechanic working on vehicle engine", "car repair shop professional", "auto repair mechanic shop"],
    "tire":       ["tire shop garage auto wheels", "car tire change service professional", "tire installation wheel auto shop", "tire store auto service"],
    "video":      ["videographer filming camera professional", "video production studio equipment", "filmmaker camera cinematic shoot", "video content creator"],
    "film":       ["videographer filming camera professional", "video production studio equipment", "filmmaker camera cinematic", "film production crew"],
    "lash":       ["lash extensions beauty salon", "eyelash studio beauty", "lash artist professional", "lash salon beauty"],
    "nail":       ["nail salon manicure professional", "nail art beauty salon", "manicure pedicure spa", "nail studio beauty"],
    "barber":     ["barbershop interior modern", "barber chair haircut", "barbershop men grooming", "barber fade haircut"],
    "taco":       ["taco restaurant mexican food", "tacos street food", "mexican restaurant interior", "taco bar food"],
    "wing":       ["chicken wings restaurant", "wings bar restaurant", "fried chicken wings", "sports bar wings"],
    "donut":      ["donut shop bakery", "doughnuts pastry shop", "donut bakery interior", "fresh donuts display"],
    "bread":      ["bakery bread fresh", "artisan bread bakery", "bread loaves bakery shop", "bakery interior bread"],
    "flower":     ["florist flower shop", "flower arrangement bouquet", "floral shop interior", "florist fresh flowers"],
    "dog":        ["dog grooming salon", "pet grooming dog", "dog spa grooming", "puppy grooming salon"],
    "car wash":   ["car wash auto detailing", "car wash service professional", "auto detailing car wash", "vehicle detailing car"],
    "detail":     ["auto detailing car wash professional", "car detailing service", "vehicle detailing exterior", "auto detailing interior"],
}

def _get_images(category: str, biz_slug: str, name: str = "") -> tuple:
    """Returns (hero_url, gal1_url, gal2_url, gal3_url, video_url)."""
    theme   = _cat(category)
    queries = list(theme.get("queries", ["professional local business"]))

    # Override queries based on keywords in the business name
    name_lower = name.lower()
    for keyword, kw_queries in _NAME_KEYWORD_QUERIES.items():
        if keyword in name_lower:
            queries = kw_queries
            break

    slug_seed = biz_slug
    images = []
    for i, q in enumerate(queries[:4]):
        url = _pexels_and_upload(q, i, biz_slug)
        images.append(url or _picsum_url(slug_seed, 1400 if i == 0 else 800, 900 if i == 0 else 600, i))

    while len(images) < 4:
        images.append(_picsum_url(slug_seed, 800, 600, len(images)))

    video_url = _pexels_video_and_upload(queries[0], biz_slug)

    return images[0], images[1], images[2], images[3], video_url


def generate_html_online(
    name: str,
    category: str,
    phone: str = "",
    city: str = "Philadelphia, PA",
    address: str = "",
) -> str:
    theme      = _cat(category)
    accent     = theme["accent"]
    dark       = theme["dark"]
    bg         = theme["bg"]
    tag        = theme["tag"]
    tagline    = theme["tagline"]
    services   = theme["services"]
    included   = theme["included"]
    reviews    = theme["reviews"]
    biz_slug   = _slug(name)

    phone_d    = phone or "(215) 555-0100"
    phone_href = re.sub(r"[^0-9+]", "", phone_d)
    city_d     = city or "Philadelphia, PA"
    short_city = city_d.split(",")[0]
    addr_d     = address.strip() or city_d
    map_q      = addr_d.replace(" ", "+").replace(",", "%2C").replace("#", "%23")
    # Escape for safe embedding in JS single-quoted strings
    name_js    = name.replace("\\", "\\\\").replace("'", "\\'")
    cat_js     = (category or "").replace("'", "\\'")

    hero_url, g1_url, g2_url, g3_url, video_url = _get_images(category, biz_slug, name)
    video_tag = (
        f'<video class="hero-vid" id="heroVid" autoplay muted loop playsinline poster="{hero_url}">'
        f'<source src="{video_url}" type="video/mp4"></video>'
    ) if video_url else ""

    svc_html = "".join(f"""
      <div class="svc-card">
        <div class="svc-icon">{ico}</div>
        <h3>{title}</h3>
        <p>{desc}</p>
      </div>""" for ico, title, desc in services)

    incl_html = "".join(f"""
      <div class="incl-item">
        <div class="incl-check">✓</div>
        <span>{item}</span>
      </div>""" for item in included)

    rev_html = "".join(f"""
      <div class="rev-card">
        <div class="rev-top">
          <div class="rev-avatar">{rev[0]}</div>
          <div>
            <div class="rev-name">{rev}</div>
            <div class="rev-stars">{"★" * stars}{"☆" * (5 - stars)}</div>
          </div>
          <img src="https://upload.wikimedia.org/wikipedia/commons/thumb/5/53/Google_%22G%22_Logo.svg/20px-Google_%22G%22_Logo.svg.png"
               style="margin-left:auto;opacity:.6;width:16px;height:16px" alt="Google" loading="lazy">
        </div>
        <p class="rev-text">{text}</p>
      </div>""" for rev, stars, text in reviews)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name} — {short_city}</title>
<!-- Google tag (GA4) — tracks which emails/categories drive mockup views -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-8VNPY96XP9"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
  gtag('config', 'G-8VNPY96XP9', {{
    page_title: '{name_js}',
    custom_map: {{'dimension1': 'business_category', 'dimension2': 'business_name'}}
  }});
  gtag('event', 'mockup_view', {{
    business_category: '{cat_js}',
    business_name: '{name_js}',
    business_city: '{short_city}'
  }});
</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{--a:{accent};--d:{dark};--bg:{bg};--surf:#111;--border:#1e1e1e;--text:#e2e2e2;--muted:#777}}
html{{scroll-behavior:smooth}}
body{{font-family:"Inter",sans-serif;background:var(--bg);color:var(--text);line-height:1.65;overflow-x:hidden}}
img{{display:block;width:100%;object-fit:cover}}
a{{color:var(--a);text-decoration:none}}

/* NAV */
nav{{position:fixed;top:0;left:0;right:0;z-index:300;height:70px;display:flex;align-items:center;
     justify-content:space-between;padding:0 6%;transition:background .3s,border-color .3s;
     border-bottom:1px solid transparent}}
nav.scrolled{{background:rgba(8,8,8,.97);backdrop-filter:blur(18px);border-color:rgba(255,255,255,.06)}}
.nav-logo{{font-family:"Playfair Display",serif;font-size:19px;font-weight:700;color:#fff;letter-spacing:-.3px}}
.nav-logo em{{color:var(--a);font-style:normal}}
.nav-links{{display:flex;gap:28px;font-size:13px;font-weight:500}}
.nav-links a{{color:#999;transition:.15s}}.nav-links a:hover{{color:#fff}}
.nav-cta{{background:var(--a);color:#080808;padding:10px 22px;border-radius:8px;
           font-weight:700;font-size:13px;letter-spacing:.2px;transition:opacity .15s,transform .15s}}
.nav-cta:hover{{opacity:.88;transform:translateY(-1px)}}
@media(max-width:768px){{.nav-links{{display:none}}}}

/* HERO */
.hero{{min-height:100vh;display:flex;align-items:center;justify-content:center;
        text-align:center;position:relative;overflow:hidden;padding:110px 6% 80px}}
.hero-bg{{position:absolute;inset:0;z-index:0;background-image:url('{hero_url}');
           background-size:cover;background-position:center;
           animation:kenBurns 28s ease-in-out infinite}}
.hero-vid{{position:absolute;inset:0;z-index:1;width:100%;height:100%;
            object-fit:cover;opacity:0;transition:opacity 1.8s ease}}
.hero-vid.loaded{{opacity:1}}
.hero-overlay{{position:absolute;inset:0;z-index:2;
  background:linear-gradient(to bottom,rgba(0,0,0,.42) 0%,{bg}bb 65%,{bg} 100%)}}
.hero-content{{position:relative;z-index:3;max-width:800px;margin:0 auto}}
.hero-badge{{display:inline-flex;align-items:center;gap:8px;
  background:rgba(255,255,255,.08);backdrop-filter:blur(10px);
  border:1px solid rgba(255,255,255,.15);border-radius:30px;
  padding:7px 18px;font-size:12px;color:rgba(255,255,255,.85);
  margin-bottom:32px;letter-spacing:.04em;font-weight:600}}
.hero-badge span{{color:var(--a)}}
.hero h1{{font-family:"Playfair Display",serif;
  font-size:clamp(2.8rem,8vw,5.5rem);font-weight:900;
  color:#fff;line-height:1.05;margin-bottom:20px;
  text-shadow:0 2px 32px rgba(0,0,0,.6)}}
.hero h1 em{{color:var(--a);font-style:normal}}
.hero-sub{{font-size:clamp(1rem,2.2vw,1.2rem);color:rgba(255,255,255,.75);
  max-width:520px;margin:0 auto 44px;line-height:1.7}}
.hero-btns{{display:flex;gap:14px;justify-content:center;flex-wrap:wrap}}
.btn-primary{{background:var(--a);color:#080808;padding:16px 38px;border-radius:10px;
  font-weight:800;font-size:15px;display:inline-flex;align-items:center;gap:8px;
  transition:opacity .15s,transform .15s}}
.btn-primary:hover{{opacity:.88;transform:translateY(-2px)}}
.btn-outline{{border:1.5px solid rgba(255,255,255,.3);color:#fff;padding:16px 36px;
  border-radius:10px;font-weight:600;font-size:15px;display:inline-flex;align-items:center;gap:8px;
  transition:border-color .15s,color .15s}}
.btn-outline:hover{{border-color:var(--a);color:var(--a)}}

/* TRUST BAR */
.trust{{background:rgba(255,255,255,.025);border-top:1px solid var(--border);
         border-bottom:1px solid var(--border);padding:28px 6%;
         display:flex;justify-content:center;flex-wrap:wrap}}
.trust-item{{text-align:center;padding:8px 40px;border-right:1px solid var(--border)}}
.trust-item:last-child{{border-right:none}}
.trust-num{{font-family:"Playfair Display",serif;font-size:28px;font-weight:700;color:var(--a)}}
.trust-label{{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;margin-top:4px}}

/* SECTIONS */
section{{padding:96px 6%}}
.eyebrow{{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.14em;color:var(--a);margin-bottom:14px}}
h2{{font-family:"Playfair Display",serif;font-size:clamp(2rem,4.5vw,3.2rem);font-weight:900;
    color:#fff;line-height:1.1;margin-bottom:16px}}
.section-sub{{font-size:1.05rem;color:var(--muted);max-width:560px;line-height:1.75;margin-bottom:56px}}

/* SERVICES */
.svc-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:20px}}
.svc-card{{background:var(--surf);border:1px solid var(--border);border-radius:16px;padding:36px 28px;
  transition:border-color .2s,transform .2s}}
.svc-card:hover{{border-color:var(--a);transform:translateY(-5px)}}
.svc-icon{{font-size:26px;width:54px;height:54px;border-radius:14px;
  background:{accent}18;display:flex;align-items:center;justify-content:center;margin-bottom:20px}}
.svc-card h3{{font-size:17px;font-weight:700;color:#fff;margin-bottom:10px}}
.svc-card p{{font-size:14px;color:#666;line-height:1.7}}

/* GALLERY */
.gallery{{display:grid;grid-template-columns:1.6fr 1fr 1fr;grid-template-rows:340px 240px;
           gap:12px;border-radius:18px;overflow:hidden}}
.gal-item{{overflow:hidden;position:relative}}
.gal-item img{{width:100%;height:100%;object-fit:cover;transition:transform .6s ease;
  background:linear-gradient(135deg,{dark},{bg})}}
.gal-item:hover img{{transform:scale(1.06)}}
.gal-item:first-child{{grid-row:1/3}}
@media(max-width:768px){{
  .gallery{{grid-template-columns:1fr 1fr;grid-template-rows:auto}}
  .gal-item:first-child{{grid-row:auto;grid-column:1/-1}}
}}

/* WHAT'S INCLUDED */
.incl-section{{background:rgba(255,255,255,.015);border-top:1px solid var(--border);border-bottom:1px solid var(--border)}}
.incl-inner{{display:grid;grid-template-columns:1fr 1fr;gap:64px;align-items:center}}
.incl-grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:8px}}
.incl-item{{display:flex;align-items:center;gap:12px;font-size:14px;color:#ccc;font-weight:500}}
.incl-check{{width:26px;height:26px;border-radius:50%;background:{accent}20;border:1px solid {accent}60;
  display:flex;align-items:center;justify-content:center;color:var(--a);font-weight:700;font-size:13px;flex-shrink:0}}
.price-card{{background:linear-gradient(135deg,{dark}22,var(--surf));
  border:1px solid {accent}50;border-radius:20px;padding:44px 40px;text-align:center}}
.price-badge{{display:inline-block;background:{accent}18;border:1px solid {accent}40;
  color:var(--a);border-radius:8px;padding:6px 16px;font-size:12px;font-weight:700;
  text-transform:uppercase;letter-spacing:.1em;margin-bottom:20px}}
.price-amount{{font-family:"Playfair Display",serif;font-size:64px;font-weight:900;color:#fff;line-height:1}}
.price-label{{color:var(--muted);font-size:14px;margin:8px 0 24px}}
.price-features{{text-align:left;margin-bottom:28px}}
.price-feature{{display:flex;align-items:center;gap:10px;padding:8px 0;
  border-bottom:1px solid {accent}20;font-size:14px;color:#bbb}}
.price-feature:last-child{{border-bottom:none}}
.price-feature span{{color:var(--a);font-weight:700}}
@media(max-width:768px){{.incl-inner{{grid-template-columns:1fr}}.incl-grid{{grid-template-columns:1fr}}}}

/* TIMELINE */
.timeline{{display:flex;justify-content:center;gap:0;flex-wrap:wrap;margin-top:48px}}
.tl-step{{display:flex;flex-direction:column;align-items:center;flex:1;min-width:140px;
           position:relative;padding:0 12px}}
.tl-step:not(:last-child)::after{{content:'→';position:absolute;right:-8px;top:28px;
  color:{accent};font-size:20px;font-weight:700}}
.tl-num{{width:56px;height:56px;border-radius:50%;
  background:linear-gradient(135deg,{accent},{dark});
  display:flex;align-items:center;justify-content:center;
  font-family:"Playfair Display",serif;font-size:22px;font-weight:900;color:#fff;
  margin-bottom:16px;box-shadow:0 0 0 6px {accent}20}}
.tl-title{{font-size:14px;font-weight:700;color:#fff;text-align:center;margin-bottom:6px}}
.tl-desc{{font-size:12px;color:var(--muted);text-align:center;line-height:1.6}}

/* REVIEWS */
.rev-bg{{background:rgba(255,255,255,.02);border-top:1px solid var(--border);border-bottom:1px solid var(--border)}}
.rev-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:20px}}
.rev-card{{background:var(--surf);border:1px solid var(--border);border-radius:16px;padding:30px 26px}}
.rev-top{{display:flex;align-items:center;gap:14px;margin-bottom:18px}}
.rev-avatar{{width:44px;height:44px;border-radius:50%;
  background:linear-gradient(135deg,{accent},{dark});
  display:flex;align-items:center;justify-content:center;
  font-size:17px;font-weight:700;color:#fff;flex-shrink:0}}
.rev-name{{font-weight:700;color:#fff;font-size:14px}}
.rev-stars{{color:#FBBC04;font-size:13px;margin-top:3px;letter-spacing:1px}}
.rev-text{{font-size:14px;color:#777;line-height:1.75;font-style:italic}}

/* CONTACT */
.contact-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-top:44px}}
.contact-card{{background:var(--surf);border:1px solid var(--border);border-radius:14px;
  padding:30px;text-align:center}}
.contact-icon{{font-size:28px;margin-bottom:12px}}
.contact-label{{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;margin-bottom:8px}}
.contact-val{{color:#ddd;font-weight:700;font-size:15px;line-height:1.5}}
.hours-row{{display:flex;justify-content:space-between;font-size:13px;padding:6px 0;
  border-bottom:1px solid var(--border)}}
.hours-row:last-child{{border-bottom:none}}
.hours-day{{color:var(--muted)}}.hours-time{{color:#ddd;font-weight:600}}
.map-wrap{{margin-top:28px;border-radius:16px;overflow:hidden;border:1px solid var(--border);height:300px}}
.map-wrap iframe{{width:100%;height:100%;border:0;display:block}}

/* CTA SECTION */
.cta-sect{{text-align:center;background:linear-gradient(135deg,{dark}25,{bg});
  border-top:1px solid {accent}30;padding:96px 6%}}
.cta-sect h2{{margin-bottom:16px}}
.cta-sect p{{color:var(--muted);margin-bottom:36px;max-width:480px;margin-left:auto;margin-right:auto}}

/* LEAD FORM */
.form-sect{{background:rgba(255,255,255,.015);border-top:1px solid var(--border)}}
.form-inner{{max-width:540px;margin:0 auto;text-align:center}}
.form-inner h2{{margin-bottom:10px}}
.form-inner p{{color:var(--muted);margin-bottom:36px}}
.lead-form{{display:flex;flex-direction:column;gap:14px;text-align:left}}
.lead-form input,.lead-form textarea{{
  background:#0f0f0f;border:1px solid #2a2a2a;border-radius:10px;
  padding:15px 18px;color:#fff;font-size:15px;font-family:"Inter",sans-serif;
  outline:none;transition:border-color .2s;width:100%}}
.lead-form input:focus,.lead-form textarea:focus{{border-color:{accent}}}
.lead-form textarea{{resize:vertical;min-height:90px}}
.lead-submit{{background:{accent};color:{bg};font-weight:800;font-size:16px;
  padding:17px;border:none;border-radius:10px;cursor:pointer;
  transition:opacity .2s,transform .15s;font-family:"Inter",sans-serif}}
.lead-submit:hover{{opacity:.88;transform:translateY(-2px)}}
.form-success{{display:none;color:{accent};font-weight:700;font-size:17px;margin-top:16px;text-align:center}}

/* FOOTER */
footer{{background:#060606;border-top:1px solid #161616;padding:36px 6%;
  display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:16px}}
.footer-logo{{font-family:"Playfair Display",serif;font-size:17px;font-weight:700;color:#fff}}
.footer-logo em{{color:{accent};font-style:normal}}
.footer-copy{{font-size:12px;color:#444}}
.footer-badge{{font-size:11px;color:#444;border:1px solid #1c1c1c;border-radius:6px;
  padding:5px 12px;background:#0a0a0a}}
.footer-badge a{{color:{accent};font-weight:600}}

/* STICKY CTA */
#sticky-cta{{position:fixed;bottom:0;left:0;right:0;z-index:400;
  background:rgba(6,6,6,.97);backdrop-filter:blur(18px);border-top:1px solid {accent}33;
  padding:14px 6%;display:flex;align-items:center;justify-content:space-between;gap:16px;
  transform:translateY(100%);transition:transform .4s cubic-bezier(.22,.68,0,1.2)}}
#sticky-cta.show{{transform:translateY(0)}}
.sticky-text{{font-size:14px;color:#888}}.sticky-text strong{{color:#fff}}
.sticky-btn{{background:var(--a);color:{bg};font-weight:800;font-size:14px;
  padding:12px 26px;border-radius:8px;white-space:nowrap;transition:opacity .15s}}
.sticky-btn:hover{{opacity:.88}}
@media(max-width:640px){{.sticky-text{{display:none}}#sticky-cta{{justify-content:center}}}}

/* WATERMARK */
.watermark{{position:fixed;bottom:72px;right:18px;z-index:200;
  background:rgba(10,10,10,.96);backdrop-filter:blur(10px);
  border:1px solid {accent}55;border-radius:10px;padding:10px 14px;
  font-size:11px;color:#aaa;box-shadow:0 4px 24px rgba(0,0,0,.6)}}
.watermark strong{{color:{accent}}}
.watermark a{{color:{accent};font-weight:600;text-decoration:none}}

/* ANIMATIONS */
@keyframes kenBurns{{
  0%   {{transform:scale(1) translate(0,0)}}
  33%  {{transform:scale(1.08) translate(-1%,-1%)}}
  66%  {{transform:scale(1.05) translate(1%,.5%)}}
  100% {{transform:scale(1) translate(0,0)}}
}}
@keyframes fadeUp{{from{{opacity:0;transform:translateY(28px)}}to{{opacity:1;transform:translateY(0)}}}}
.hero-content>*{{opacity:0;animation:fadeUp .7s cubic-bezier(.22,.68,0,1.2) forwards}}
.hero-content .hero-badge{{animation-delay:.1s}}
.hero-content h1{{animation-delay:.25s}}
.hero-content .hero-sub{{animation-delay:.4s}}
.hero-content .hero-btns{{animation-delay:.55s}}
[data-reveal]{{opacity:0;transform:translateY(36px);transition:opacity .7s ease,transform .7s ease;animation:fadeUp .8s ease .4s both}}
[data-reveal].visible{{opacity:1;transform:translateY(0);animation:none}}
</style>
</head>
<body>

<!-- NAV -->
<nav id="nav">
  <div class="nav-logo">{name.split()[0]}<em>{"".join(name.split()[1:]) or ""}</em></div>
  <div class="nav-links">
    <a href="#services">Services</a>
    <a href="#gallery">Gallery</a>
    <a href="#reviews">Reviews</a>
    <a href="#contact">Contact</a>
  </div>
  <a href="tel:{phone_href}" class="nav-cta">📞 Call Now</a>
</nav>

<!-- HERO -->
<section class="hero">
  <div class="hero-bg"></div>
  {video_tag}
  <div class="hero-overlay"></div>
  <div class="hero-content">
    <div class="hero-badge"><span>{tag}</span>&nbsp;·&nbsp;{short_city}, PA</div>
    <h1>{name}</h1>
    <p class="hero-sub">{tagline} — proudly serving {short_city} and the surrounding area.</p>
    <div class="hero-btns">
      <a href="tel:{phone_href}" class="btn-primary">📞 {phone_d}</a>
      <a href="#get-started" class="btn-outline">Get This Website →</a>
    </div>
  </div>
</section>

<!-- TRUST BAR -->
<div class="trust" data-reveal>
  <div class="trust-item"><div class="trust-num">10+</div><div class="trust-label">Years Serving {short_city}</div></div>
  <div class="trust-item"><div class="trust-num">500+</div><div class="trust-label">Happy Customers</div></div>
  <div class="trust-item"><div class="trust-num">5★</div><div class="trust-label">Google Rating</div></div>
  <div class="trust-item"><div class="trust-num">Same Day</div><div class="trust-label">Response</div></div>
</div>

<!-- SERVICES -->
<section id="services">
  <p class="eyebrow" data-reveal>What We Offer</p>
  <h2 data-reveal>Our Services</h2>
  <p class="section-sub" data-reveal>Every service is delivered with the care and expertise your business deserves.</p>
  <div class="svc-grid">{svc_html}</div>
</section>

<!-- GALLERY -->
<section id="gallery" style="padding-top:0">
  <div class="gallery">
    <div class="gal-item"><img src="{g1_url}" alt="{name} gallery" loading="lazy" onerror="this.style.background='linear-gradient(135deg,{dark},{bg})';this.style.display='block';this.remove()"></div>
    <div class="gal-item"><img src="{g2_url}" alt="{name} gallery" loading="lazy" onerror="this.style.background='linear-gradient(135deg,{accent}33,{bg})';this.remove()"></div>
    <div class="gal-item"><img src="{g3_url}" alt="{name} gallery" loading="lazy" onerror="this.style.background='linear-gradient(135deg,{dark},{accent}44)';this.remove()"></div>
  </div>
</section>

<!-- WHAT'S INCLUDED -->
<section class="incl-section">
  <div class="incl-inner">
    <div>
      <p class="eyebrow" data-reveal>Your New Website Includes</p>
      <h2 data-reveal>Everything You Need to Get Found Online</h2>
      <p class="section-sub" data-reveal>No hidden fees, no monthly charges. One flat price — ready to launch in 7 days.</p>
      <div class="incl-grid" data-reveal>{incl_html}</div>
    </div>
    <div class="price-card" data-reveal>
      <div class="price-badge">Starting at $499 — No Monthly Fees</div>
      <div class="price-amount">$499</div>
      <div class="price-label">One-time price &nbsp;·&nbsp; No surprises</div>
      <div class="price-features">
        <div class="price-feature"><span>✓</span> Custom design for your business</div>
        <div class="price-feature"><span>✓</span> Mobile-ready & fast loading</div>
        <div class="price-feature"><span>✓</span> Google-optimized (SEO)</div>
        <div class="price-feature"><span>✓</span> Live in 7 days</div>
        <div class="price-feature"><span>✓</span> 30-day support included</div>
      </div>
      <a href="#get-started" class="btn-primary" style="display:flex;justify-content:center">I Want This Site →</a>
    </div>
  </div>
</section>

<!-- TIMELINE -->
<section style="text-align:center">
  <p class="eyebrow" data-reveal>How It Works</p>
  <h2 data-reveal>Live in 7 Days</h2>
  <p class="section-sub" data-reveal style="margin:0 auto 0">Three simple steps. No tech skills needed from you.</p>
  <div class="timeline" data-reveal>
    <div class="tl-step">
      <div class="tl-num">1</div>
      <div class="tl-title">You Say Yes</div>
      <div class="tl-desc">Fill out a 5-minute form with your business details. That's it.</div>
    </div>
    <div class="tl-step">
      <div class="tl-num">2</div>
      <div class="tl-title">We Build It</div>
      <div class="tl-desc">Maya designs your custom site and sends a preview within 3 days.</div>
    </div>
    <div class="tl-step">
      <div class="tl-num">3</div>
      <div class="tl-title">You Go Live</div>
      <div class="tl-desc">Approve the design and your site is live within 7 days — guaranteed.</div>
    </div>
  </div>
</section>

<!-- REVIEWS -->
<section id="reviews" class="rev-bg">
  <p class="eyebrow" data-reveal>What People Say</p>
  <h2 data-reveal>Google Reviews</h2>
  <p class="section-sub" data-reveal>Real customers, real results.</p>
  <div class="rev-grid">{rev_html}</div>
</section>

<!-- CONTACT & MAP -->
<section id="contact">
  <p class="eyebrow">Find Us</p>
  <h2>Hours &amp; Location</h2>
  <div class="contact-grid">
    <div class="contact-card">
      <div class="contact-icon">📞</div>
      <div class="contact-label">Phone</div>
      <div class="contact-val"><a href="tel:{phone_href}" style="color:#ddd">{phone_d}</a></div>
    </div>
    <div class="contact-card">
      <div class="contact-icon">📍</div>
      <div class="contact-label">Address</div>
      <div class="contact-val">{addr_d}</div>
    </div>
    <div class="contact-card" style="grid-column:span 2">
      <div class="contact-icon">🕐</div>
      <div class="contact-label" style="margin-bottom:16px">Hours</div>
      <div class="hours-row"><span class="hours-day">Monday – Friday</span><span class="hours-time">9:00 AM – 7:00 PM</span></div>
      <div class="hours-row"><span class="hours-day">Saturday</span><span class="hours-time">9:00 AM – 5:00 PM</span></div>
      <div class="hours-row"><span class="hours-day">Sunday</span><span class="hours-time">Closed</span></div>
    </div>
  </div>
  <div class="map-wrap" data-reveal>
    <iframe src="https://maps.google.com/maps?q={map_q}&output=embed&z=15"
      allowfullscreen loading="lazy" referrerpolicy="no-referrer-when-downgrade"></iframe>
  </div>
</section>

<!-- CTA -->
<section class="cta-sect">
  <p class="eyebrow" data-reveal>Ready?</p>
  <h2 data-reveal>Get {name}'s Website Live in 7 Days</h2>
  <p data-reveal>Starting at $499. No monthly fees. No tech skills needed.</p>
  <a href="#get-started" class="btn-primary" style="display:inline-flex;margin:0 auto" data-reveal>Claim This Design →</a>
</section>

<!-- LEAD FORM -->
<section class="form-sect" id="get-started">
  <div class="form-inner">
    <p class="eyebrow">Free Preview — No Commitment</p>
    <h2>Let's Build Your Website</h2>
    <p>Leave your info and Maya will reach out within 24 hours.</p>
    <form class="lead-form" id="leadForm">
      <input type="text" name="name" placeholder="Your name" required>
      <input type="email" name="email" placeholder="Your email" required>
      <input type="tel" name="phone" placeholder="Your phone (optional)">
      <textarea name="message" placeholder="Any questions or special requests? (optional)"></textarea>
      <button type="submit" class="lead-submit">Yes, I Want This Website →</button>
    </form>
    <div class="form-success" id="formSuccess">✅ Got it! Maya will reach out within 24 hours.</div>
  </div>
</section>

<!-- FOOTER -->
<footer>
  <div class="footer-logo">{name.split()[0]}<em>{"".join(name.split()[1:]) or ""}</em></div>
  <span class="footer-copy">© 2026 {name} · {city_d}</span>
  <div class="footer-badge">Preview by <a href="https://webbymaya.com" target="_blank">WebByMaya.com</a> · <a href="mailto:maya@webbymaya.com">maya@webbymaya.com</a></div>
</footer>

<div id="sticky-cta">
  <div class="sticky-text">Like this design? <strong>Claim it for your business.</strong></div>
  <a href="#get-started" class="sticky-btn">Get This Site — Starting at $499</a>
</div>
<div class="watermark">Preview by <strong>WebByMaya</strong><br><a href="mailto:maya@webbymaya.com">maya@webbymaya.com</a></div>

<script>
// Hero video fade-in
const heroVid = document.getElementById('heroVid');
if (heroVid) {{
  heroVid.addEventListener('canplay', () => heroVid.classList.add('loaded'), {{once:true}});
  // Fallback: force-show after 4s if event misfires
  setTimeout(() => heroVid.classList.add('loaded'), 4000);
}}

// Nav scroll
const nav = document.getElementById('nav');
window.addEventListener('scroll', () => {{
  nav.classList.toggle('scrolled', window.scrollY > 70);
}}, {{passive:true}});

// Sticky CTA after hero
const hero    = document.querySelector('.hero');
const stickyCta = document.getElementById('sticky-cta');
new IntersectionObserver(([e]) => stickyCta.classList.toggle('show', !e.isIntersecting),
  {{threshold:0}}).observe(hero);

// Scroll reveals
new IntersectionObserver((entries) => {{
  entries.forEach(el => {{
    if (el.isIntersecting) {{ el.target.classList.add('visible'); }}
  }});
}}, {{threshold:.12}}).observe(document.querySelectorAll('[data-reveal]'));
// Fix — observe all reveals
document.querySelectorAll('[data-reveal]').forEach(el => {{
  new IntersectionObserver(([e]) => {{ if (e.isIntersecting) e.target.classList.add('visible'); }},
    {{threshold:.1}}).observe(el);
}});

// Lead form
document.getElementById('leadForm').addEventListener('submit', function(e) {{
  e.preventDefault();
  const data = Object.fromEntries(new FormData(this));
  const payload = {{
    business: '{name_js}',
    name:     data.name    || '',
    email:    data.email   || '',
    phone:    data.phone   || '',
    message:  data.message || '',
    source:   'mockup_preview',
  }};
  // Save lead directly to Supabase
  fetch('https://ycsauzlqsjjbusugshpz.supabase.co/rest/v1/mockup_leads', {{
    method: 'POST',
    headers: {{
      'Content-Type':  'application/json',
      'apikey':        'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inljc2F1emxxc2pqYnVzdWdzaHB6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk0NjMzMTQsImV4cCI6MjA5NTAzOTMxNH0._rjYuGZch-CA4sfm2rV3lvs_ixDcQfNFg90KWsbe1HI',
      'Authorization': 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inljc2F1emxxc2pqYnVzdWdzaHB6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk0NjMzMTQsImV4cCI6MjA5NTAzOTMxNH0._rjYuGZch-CA4sfm2rV3lvs_ixDcQfNFg90KWsbe1HI',
      'Prefer':        'return=minimal',
    }},
    body: JSON.stringify(payload),
  }}).catch(() => {{}});
  this.style.display = 'none';
  document.getElementById('formSuccess').style.display = 'block';
}});
</script>
</body>
</html>"""


GITHUB_PAGES_BASE = "https://mayasworldwideweb.github.io/previews"
GITHUB_REPO       = "MayasWorldWideWeb/previews"
GITHUB_REPO_PATH  = "/tmp/previews-repo"

def _token_slug(name: str) -> str:
    """Return slug with a 6-char hash token — non-guessable, stable per business name."""
    base  = _slug(name)
    token = hashlib.md5(name.lower().strip().encode()).hexdigest()[:6]
    return f"{base}-{token}"

def upload_mockup(
    name: str,
    category: str,
    phone: str = "",
    city: str = "Philadelphia, PA",
    address: str = "",
) -> str:
    """Generate a mockup HTML file and push to GitHub Pages. Returns public URL or ''."""
    import subprocess, pathlib
    biz_slug = _token_slug(name)
    filename = f"{biz_slug}.html"
    html     = generate_html_online(name, category, phone, city, address)

    repo = pathlib.Path(GITHUB_REPO_PATH)
    # Clone repo if not present
    if not (repo / ".git").exists():
        subprocess.run(
            ["git", "clone", f"https://github.com/{GITHUB_REPO}.git", str(repo)],
            capture_output=True, check=True)

    out = repo / filename
    out.write_text(html, encoding="utf-8")

    try:
        subprocess.run(["git", "-C", str(repo), "add", filename], capture_output=True, check=True)
        result = subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", f"add {filename}"],
            capture_output=True, text=True)
        if "nothing to commit" not in result.stdout:
            subprocess.run(["git", "-C", str(repo), "push"], capture_output=True, check=True)
        pub = f"{GITHUB_PAGES_BASE}/{filename}"
        print(f"  Mockup  : {pub}")
        return pub
    except Exception as exc:
        print(f"  [mockup] push failed: {exc}")
        return ""


if __name__ == "__main__":
    import sys
    name     = sys.argv[1] if len(sys.argv) > 1 else "Fancy Nail Salon"
    category = sys.argv[2] if len(sys.argv) > 2 else "nail salon"
    phone    = sys.argv[3] if len(sys.argv) > 3 else "(215) 555-0100"
    address  = sys.argv[4] if len(sys.argv) > 4 else "1234 Main St, Philadelphia, PA 19103"
    url = upload_mockup(name, category, phone, address=address)
    print(f"URL: {url}" if url else "Upload failed.")

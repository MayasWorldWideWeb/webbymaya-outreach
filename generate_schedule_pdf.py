#!/usr/bin/env python3
"""Generate WebByMaya 30-day Instagram content calendar PDF."""
from fpdf import FPDF
from datetime import date, timedelta

START = date(2026, 6, 10)
DAYS  = 30

POSTS = [
    {
        "image": "Is Your Business Invisible Online?",
        "caption": (
            "No website = invisible to every customer searching right now.\n\n"
            "Most Philly businesses lose clients daily to competitors who just… "
            "have a website.\n\n"
            "I fix that. Starting at $499. Live in 7 days. You own everything.\n\n"
            ">> Link in bio to get started.\n\n"
            "#PhillySmallBusiness #WebDesign #Philadelphia #SmallBizPhilly #WebbyMaya"
        ),
    },
    {
        "image": "Salon Owners — Your Clients Are Searching",
        "caption": (
            "Philly salon owners — your next client is Googling right now.\n\n"
            "If you don't have a website, they're booking with someone who does.\n\n"
            "I build beautiful, booking-ready websites for salons and spas "
            "in the Philadelphia area. Starting at $799.\n\n"
            "Fill out my intake form — link in bio\n\n"
            "#PhillySalon #NailSalon #HairSalon #PhillyBeauty #WebbyMaya"
        ),
    },
    {
        "image": "Your Food Deserves to Be Found",
        "caption": (
            "People Google where they're eating before they leave the house.\n\n"
            "No website? You're not even in the running.\n\n"
            "I build restaurant websites with your menu, hours, and location "
            "— starting at $799, live in 7 days.\n\n"
            "Link in bio \n\n"
            "#PhillyRestaurant #PhillyFood #RestaurantOwner #PhillyEats #WebbyMaya"
        ),
    },
    {
        "image": "97% Stat Post",
        "caption": (
            "97% of consumers search online before visiting a local business.\n\n"
            "If you don't have a website, you're handing customers to whoever does.\n\n"
            "I build fast, clean, mobile-ready websites for Philly businesses "
            "— $799, live in 7 days.\n\n"
            "Link in bio. Let's fix it. \n\n"
            "#PhillySmallBusiness #WebDesign #LocalBusiness #Philly #WebbyMaya"
        ),
    },
    {
        "image": "Philly Runs on Small Businesses",
        "caption": (
            "Philly runs on small businesses.\n\n"
            "The corner store. The salon. The mechanic. The spot everyone "
            "in the neighborhood knows.\n\n"
            "You work too hard to be invisible online. A website shouldn't cost "
            "a fortune — mine start at $799 and go live in 7 days.\n\n"
            "Let's get you out there. Link in bio \n\n"
            "#Philadelphia #PhillyBusiness #SmallBusiness #SupportLocal #WebbyMaya"
        ),
    },
    {
        "image": "Before/After — No Website vs webbymaya.com",
        "caption": (
            "No website = invisible to every customer searching right now.\n\n"
            "35% of customers won't visit a business they can't find online.\n\n"
            "Fix that. $799. Live in 7 days.\n\n"
            ">> webbymaya.com — link in bio\n\n"
            "#WebDesign #Philadelphia #SmallBusiness #PhillyBusiness #WebbyMaya"
        ),
    },
    {
        "image": "Don't Be Result #3",
        "caption": (
            "Your customers are searching right now.\n\n"
            "The question is — are they finding you, or your competitor?\n\n"
            "I build websites for Philly small businesses that actually show up "
            "on Google. Starting at $799.\n\n"
            "Don't be invisible. Link in bio \n\n"
            "#PhillyBusiness #GoogleSearch #SEO #SmallBusiness #WebbyMaya"
        ),
    },
    {
        "image": "When Someone's Car Breaks Down, They Google",
        "caption": (
            "Auto shop owners — when someone's car breaks down, the first thing "
            "they do is Google a mechanic nearby.\n\n"
            "Is your shop coming up?\n\n"
            "I build websites for Philly auto shops and mechanics. Fast, "
            "affordable, shows up on Google. Starting at $799.\n\n"
            "Link in bio \n\n"
            "#PhillyAutoRepair #AutoShop #Mechanic #PhillyBusiness #WebbyMaya"
        ),
    },
    {
        "image": "Your Work Deserves More Than a Facebook Page",
        "caption": (
            "Photographers — your work deserves more than a Facebook page.\n\n"
            "A portfolio website gets you discovered on Google, books more "
            "clients, and makes you look like the pro you are.\n\n"
            "Starting at $799 — live in 7 days.\n\n"
            "Link in bio \n\n"
            "#PhillyPhotographer #PhotographyWebsite #PhillyPhotography "
            "#WebDesign #WebbyMaya"
        ),
    },
    {
        "image": "FAQ: Do I Really Need a Website?",
        "caption": (
            "Let me answer this once and for all.\n\n"
            "Q: I have Facebook. A: Not the same thing.\n"
            "Q: It costs too much. A: Starting at $499. That's it.\n"
            "Q: It takes forever. A: 7 days. Done.\n\n"
            "Any other objections? Link in bio \n\n"
            "#WebDesign #Philly #SmallBusiness #PhillyBusiness #WebbyMaya"
        ),
    },
    {
        "image": "Summer Is the Busiest Season",
        "caption": (
            "Summer is the busiest season — is your business ready?\n\n"
            "Tourists, locals, and everyone in between is searching for things "
            "to do and places to go in Philly this summer.\n\n"
            "Make sure they find YOU. Website from $799, live in 7 days.\n\n"
            "Link in bio \n\n"
            "#PhillyBusiness #PhillySummer #SmallBusiness #Philadelphia #WebbyMaya"
        ),
    },
    {
        "image": "$0 Stat Post",
        "caption": (
            "$0 — that's how much new business you get from customers who "
            "can't find you online.\n\n"
            "A WebByMaya website changes that.\n\n"
            "Starting at $499. Live in 7 days. Philly · South Jersey · Delaware.\n\n"
            "webbymaya.com — link in bio\n\n"
            "#PhillySmallBusiness #WebDesign #LocalBusiness #Philly #WebbyMaya"
        ),
    },
    {
        "image": "$799 — What You Actually Get",
        "caption": (
            "What does a $799 website actually get you?\n\n"
            "[x] Custom design built for your business\n"
            "[x] Works on phones (where your customers are)\n"
            "[x] Shows up on Google\n"
            "[x] Your domain, your hosting — you own it\n"
            "[x] Live in 7 days\n\n"
            "No monthly payments to me. No fluff.\n\n"
            "See what you get → link in bio\n\n"
            "#WebDesign #Philly #SmallBusiness #Affordable #WebbyMaya"
        ),
    },
    {
        "image": "Google Your Restaurant",
        "caption": (
            "Quick challenge — Google your restaurant right now.\n\n"
            "What comes up? A Yelp page you didn't set up? Nothing?\n\n"
            "Your customers are doing this every day before they decide "
            "where to eat. Make sure they find you.\n\n"
            "Restaurant websites from $799. Link in bio \n\n"
            "#PhillyRestaurant #PhillyEats #RestaurantOwner #PhillyFood #WebbyMaya"
        ),
    },
    {
        "image": "Is Your Business Invisible Online? (repeat)",
        "caption": (
            "If someone searches for your type of business right now, "
            "will they find you — or your competitor?\n\n"
            "I build affordable websites for local businesses in Philadelphia, "
            "South Jersey, and Delaware. Starting at $799, live in 7 days.\n\n"
            ">> Link in bio\n\n"
            "#PhillySmallBusiness #WebDesign #Philadelphia #SmallBizPhilly #WebbyMaya"
        ),
    },
    {
        "image": "Salon Owners (repeat)",
        "caption": (
            "Salon owners — your clients are searching "
            "\"nail salon near me\" right now.\n\n"
            "If you don't have a website, you're invisible.\n\n"
            "I build websites specifically for salons in the Philly area. "
            "Starting at $799.\n\n"
            "See what you'd get → link in bio \n\n"
            "#PhillySalon #NailSalon #HairSalon #PhillyBeauty #WebbyMaya"
        ),
    },
    {
        "image": "Philly Community (repeat)",
        "caption": (
            "To every Philly shop owner, salon, mechanic, restaurant, and "
            "photographer grinding daily — you deserve to be found online.\n\n"
            "A website shouldn't cost a fortune. Mine start at $799 "
            "and go live in 7 days.\n\n"
            "Let's get you out there → link in bio\n\n"
            "#PhillyBusiness #Entrepreneur #SmallBusiness #Philadelphia #WebbyMaya"
        ),
    },
    {
        "image": "Before/After (repeat)",
        "caption": (
            "Two businesses. Same neighborhood. Same type of shop.\n\n"
            "One has a website. One doesn't.\n\n"
            "Guess which one gets the call?\n\n"
            "$799. 7 days. webbymaya.com — link in bio.\n\n"
            "#WebDesign #Philadelphia #SmallBusiness #PhillyBusiness #WebbyMaya"
        ),
    },
    {
        "image": "Don't Be Result #3 (repeat)",
        "caption": (
            "Free tip: Google your business name right now.\n\n"
            "If it's nothing — or a Yelp page you didn't set up — "
            "you need a website.\n\n"
            "I build them for $799. Takes a week. You keep full ownership.\n\n"
            "More info → link in bio\n\n"
            "#GoogleMyBusiness #WebDesign #Philadelphia #SmallBusiness #WebbyMaya"
        ),
    },
    {
        "image": "Auto Shop (repeat)",
        "caption": (
            "Philly mechanics and auto shops — this one's for you.\n\n"
            "When someone's car breaks down they Google \"auto repair near me\" "
            "from their phone on the side of the road.\n\n"
            "If your shop doesn't have a website, you're not in those results.\n\n"
            "Starting at $799 → link in bio \n\n"
            "#PhillyAutoRepair #AutoShop #Mechanic #PhillyBusiness #WebbyMaya"
        ),
    },
    {
        "image": "97% Stat (repeat)",
        "caption": (
            "The #1 thing I hear from Philly business owners:\n\n"
            "\"I know I need a website, I just haven't gotten around to it.\"\n\n"
            "I make it easy. You answer a few questions, I handle everything, "
            "you go live in 7 days. Starting at $799.\n\n"
            "Fill out my intake form → link in bio\n\n"
            "#PhillySmallBusiness #WebsiteDesign #LocalBusiness #WebbyMaya"
        ),
    },
    {
        "image": "South Jersey Businesses",
        "caption": (
            "South Jersey business owners \n\n"
            "Cherry Hill, Camden, Voorhees, Mount Laurel — I've got you covered.\n\n"
            "Same quality websites as Philly, same $799 price, "
            "same 7-day turnaround.\n\n"
            "Link in bio\n\n"
            "#SouthJersey #CherryHill #CamdenNJ #SmallBusiness #WebbyMaya"
        ),
    },
    {
        "image": "Summer (repeat)",
        "caption": (
            "Philly summers bring foot traffic, tourists, and new customers "
            "searching for local spots.\n\n"
            "Don't let them scroll past you because you have no website.\n\n"
            "Get online before summer peaks. $799 — live in 7 days.\n\n"
            "Link in bio \n\n"
            "#PhillySummer #PhillyBusiness #SmallBusiness #Philadelphia #WebbyMaya"
        ),
    },
    {
        "image": "FAQ (repeat)",
        "caption": (
            "Still on the fence about a website? Let me break it down.\n\n"
            "- Cost: starting at $499 — no monthly fees to me\n"
            "- Time: 7 days from start to live\n"
            "- Ownership: Your domain, your hosting, yours forever\n"
            "- Results: Shows up on Google, works on phones\n\n"
            "Ready? Link in bio.\n\n"
            "#WebDesign #Philly #SmallBusiness #Affordable #WebbyMaya"
        ),
    },
    {
        "image": "Photographer (repeat)",
        "caption": (
            "Philly photographers — a Facebook page is not a portfolio.\n\n"
            "A website is.\n\n"
            "I build photography websites that show off your work, "
            "get you inquiries, and rank on Google. From $799.\n\n"
            "Link in bio \n\n"
            "#PhillyPhotographer #PhotographyWebsite #WebDesign #WebbyMaya"
        ),
    },
    {
        "image": "Delaware Businesses",
        "caption": (
            "Delaware small businesses — don't sleep on this.\n\n"
            "Wilmington, Newark, Dover — I cover all of Delaware too.\n\n"
            "If your business doesn't have a website, I can fix that "
            "in 7 days for $799.\n\n"
            "Free consultation → link in bio \n\n"
            "#DelawareBusiness #Wilmington #SmallBusiness #WebDesign #WebbyMaya"
        ),
    },
    {
        "image": "$799 Value Breakdown (repeat)",
        "caption": (
            "People always ask — what exactly do I get for $799?\n\n"
            "Here's the answer:\n\n"
            "[x] Custom design (not a template)\n"
            "[x] Mobile-optimized\n"
            "[x] Google-ready from day one\n"
            "[x] You own the domain and hosting\n"
            "[x] Live in 7 days\n\n"
            "That's it. No surprises. Link in bio.\n\n"
            "#WebDesign #Philadelphia #SmallBusiness #Affordable #WebbyMaya"
        ),
    },
    {
        "image": "$0 Stat (repeat)",
        "caption": (
            "Every day you don't have a website is a day you're leaving "
            "money on the table.\n\n"
            "Customers can't call you if they can't find you.\n\n"
            "I fix that for $799. Done in 7 days.\n\n"
            "Philly · South Jersey · Delaware\n\n"
            "webbymaya.com — link in bio\n\n"
            "#PhillySmallBusiness #WebDesign #LocalBusiness #Philly #WebbyMaya"
        ),
    },
    {
        "image": "Philly Community (final)",
        "caption": (
            "Shoutout to every Philly small business owner making it work.\n\n"
            "You're the reason this city has character. And you deserve "
            "to be found by every person searching for what you offer.\n\n"
            "Let's get your business online. $799. 7 days.\n\n"
            "Link in bio \n\n"
            "#Philadelphia #PhillyBusiness #SmallBusiness #SupportLocal #WebbyMaya"
        ),
    },
    {
        "image": "Is Your Business Invisible? (final)",
        "caption": (
            "July is here. New month, fresh start.\n\n"
            "If getting a website has been on your list — this is your sign.\n\n"
            "Starting at $499. Live in 7 days. No monthly fees.\n\n"
            "Fill out my intake form → link in bio\n\n"
            "#PhillySmallBusiness #WebDesign #NewMonth #SmallBusiness #WebbyMaya"
        ),
    },
]

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS   = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# ── Colors ──────────────────────────────────────────────────────────────────
BLACK      = (0,   0,   0)
WHITE      = (255, 255, 255)
ACCENT     = (99,  60, 219)   # WebByMaya purple
LIGHT_GREY = (245, 245, 247)
MID_GREY   = (180, 180, 185)
DARK_GREY  = (60,  60,  65)


FONT_PATH = "/Library/Fonts/Arial Unicode.ttf"


class PDF(FPDF):
    def header(self):
        pass

    def footer(self):
        self.set_y(-12)
        self.set_font("AU", "", 8)
        self.set_text_color(*MID_GREY)
        self.cell(0, 10, f"WebByMaya - Content Calendar - Page {self.page_no()}", align="C")


def make_pdf(output_path: str):
    pdf = PDF(orientation="P", unit="mm", format="A4")
    pdf.add_font("AU", "", FONT_PATH)
    pdf.add_font("AU", "B", FONT_PATH)
    pdf.add_font("AU", "I", FONT_PATH)
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(15, 15, 15)

    # ── Cover page ────────────────────────────────────────────────────────
    pdf.add_page()
    pdf.set_fill_color(*ACCENT)
    pdf.rect(0, 0, 210, 297, "F")

    pdf.set_y(80)
    pdf.set_font("AU", "B", 38)
    pdf.set_text_color(*WHITE)
    pdf.cell(0, 14, "WebByMaya", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("AU", "", 18)
    pdf.set_text_color(220, 210, 255)
    pdf.cell(0, 10, "30-Day Instagram Content Calendar", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(4)
    pdf.set_font("AU", "", 13)
    pdf.set_text_color(*WHITE)
    pdf.cell(0, 8, "June 10 - July 9, 2026", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(40)
    pdf.set_font("AU", "", 11)
    pdf.set_text_color(200, 190, 240)
    pdf.cell(0, 7, "webbymaya.com", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, "Philadelphia - South Jersey - Delaware", align="C")

    # ── How to use page ───────────────────────────────────────────────────
    pdf.add_page()
    pdf.set_font("AU", "B", 20)
    pdf.set_text_color(*ACCENT)
    pdf.cell(0, 10, "How to Use This Calendar", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    pdf.set_draw_color(*ACCENT)
    pdf.set_line_width(0.8)
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    pdf.ln(6)

    tips = [
        ("  Scheduling", "Upload each image + caption to Meta Business Suite (business.facebook.com) and schedule one post per day. Set times between 9–11 AM or 6–8 PM for best reach."),
        ("  Images", "Each day lists the image name. Download the matching design from your Canva account and upload it to Meta."),
        ("  Captions", "Captions are ready to copy-paste. Feel free to add personal touches — the more authentic it sounds, the better it performs."),
        ("  Repeats", "Some posts repeat with fresh captions. Rotating proven content is normal and effective — your audience grows daily so new followers see it for the first time."),
        ("#  Hashtags", "Hashtags are included in every caption. Don't remove them — they extend reach to people not following you yet."),
        ("  Link in Bio", "Make sure webbymaya.com is set as your Instagram bio link before posts go live."),
    ]

    for title, body in tips:
        pdf.set_font("AU", "B", 12)
        pdf.set_text_color(*BLACK)
        pdf.cell(0, 7, title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("AU", "", 10)
        pdf.set_text_color(*DARK_GREY)
        pdf.multi_cell(0, 6, body)
        pdf.ln(3)

    # ── Daily schedule pages ──────────────────────────────────────────────
    for i in range(DAYS):
        day_date   = START + timedelta(days=i)
        weekday    = WEEKDAYS[day_date.weekday()]
        month_name = MONTHS[day_date.month]
        post       = POSTS[i % len(POSTS)]

        pdf.add_page()

        # Day header bar
        pdf.set_fill_color(*ACCENT)
        pdf.rect(0, 0, 210, 22, "F")
        pdf.set_y(5)
        pdf.set_font("AU", "B", 14)
        pdf.set_text_color(*WHITE)
        pdf.cell(0, 12,
                 f"Day {i+1}  ·  {weekday} {month_name} {day_date.day}",
                 align="C")

        pdf.ln(6)

        # Image label box
        pdf.set_fill_color(*LIGHT_GREY)
        pdf.set_draw_color(*MID_GREY)
        pdf.set_line_width(0.3)
        pdf.set_x(15)
        pdf.set_font("AU", "B", 9)
        pdf.set_text_color(*ACCENT)
        pdf.cell(180, 7, "  IMAGE", fill=True, border=1,
                 new_x="LMARGIN", new_y="NEXT")
        pdf.set_x(15)
        pdf.set_font("AU", "", 11)
        pdf.set_text_color(*BLACK)
        pdf.cell(180, 10, f"  {post['image']}", border=1,
                 fill=False, new_x="LMARGIN", new_y="NEXT")

        pdf.ln(5)

        # Caption box
        pdf.set_x(15)
        pdf.set_font("AU", "B", 9)
        pdf.set_text_color(*ACCENT)
        pdf.set_fill_color(*LIGHT_GREY)
        pdf.cell(180, 7, "  CAPTION (copy & paste)", fill=True, border=1,
                 new_x="LMARGIN", new_y="NEXT")

        pdf.set_x(15)
        pdf.set_font("AU", "", 10)
        pdf.set_text_color(*DARK_GREY)
        # Write caption inside a bordered multi_cell
        caption_lines = post["caption"]
        x_before = pdf.get_x()
        y_before  = pdf.get_y()
        pdf.multi_cell(180, 6, caption_lines, border=1, fill=False)

        pdf.ln(5)

        # Notes line
        pdf.set_x(15)
        pdf.set_font("AU", "B", 9)
        pdf.set_text_color(*ACCENT)
        pdf.set_fill_color(*LIGHT_GREY)
        pdf.cell(180, 7, "  NOTES / SCHEDULED TIME", fill=True, border=1,
                 new_x="LMARGIN", new_y="NEXT")
        pdf.set_x(15)
        pdf.set_font("AU", "", 10)
        pdf.set_text_color(*MID_GREY)
        pdf.cell(180, 10, "  _______________________________________________________   ____________", border=1)

    pdf.output(output_path)
    print(f"PDF saved to: {output_path}")


if __name__ == "__main__":
    import os
    out = os.path.expanduser("~/Desktop/WebByMaya_Content_Calendar_June-July_2026.pdf")
    make_pdf(out)

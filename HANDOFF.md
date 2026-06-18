# WebByMaya — Session Handoff
**Date:** June 9, 2026  
**Status:** Marketing automation running. One item left to activate (Instagram).

---

## What's Running Right Now (Fully Automatic)

| Time | What | Status |
|---|---|---|
| 9 AM daily | Find prospects → enrich → send emails + SMS | ✅ Running |
| 9 AM daily | Email follow-ups to warm leads (safe emails only) | ✅ Running |
| 9 AM daily | SMS follow-ups | ✅ Running |
| Noon daily | Follow 30 Philly businesses on Instagram | ✅ Scheduled (needs first login) |
| Mon/Wed/Fri 11 AM | Auto-post to Instagram | ✅ Scheduled (needs first login) |
| Monday 8 AM | Weekly summary email to mayasierra1999@gmail.com | ✅ Running |

---

## Your Shell Commands (open any terminal tab)

```bash
wm-status      # all-time campaign stats
wm-replies     # check Gmail for replies + Mac notification
wm-summary     # today's outreach breakdown
wm-followup    # manually trigger email follow-ups
```

---

## What Was Done Today

### Outreach
- Sent **10 follow-up emails** to warm leads (businesses first contacted May 30)
  - Coker Photography, Louder Than Bombs Tattoo, Fancy Nail, Luigi's, Love Nails & Spa,
    Happy Paws Pet Lounge, Higbee Automotive, J&A Auto Services, Lavish Nail & Spa, Ann's Nail Salon
- Updated cold email subject from generic → personalized: `"Quick question, {Business Name}"`
- Built `email_followups.py` — runs daily automatically, filters junk emails

### Zone Expansion
- Was: 13 zones (7 done, 6 left)
- Now: **23 zones** (7 done, 16 left)
- Added: Montgomery County, Delaware County, Bucks County, Chester County PA + 2 more NJ zones
- Pipeline runs automatically — nothing to do

### New Scripts Built
| Script | What it does |
|---|---|
| `email_followups.py` | Follow-up emails to 7-day-old leads (auto, daily) |
| `check_replies.py` | Scans Gmail for replies from contacted businesses |
| `wm_status.py` | All-time campaign dashboard |
| `weekly_summary.py` | Monday morning email digest (fixed from SMS → email) |
| `craigslist_poster.py` | Built but skipped — Philly posts cost $5 each |
| `instagram_poster.py` | Auto-posts 3x/week, 12 rotating captions ready |
| `follow_prospects.py` | Auto-follows 30 Philly businesses/day on Instagram |

### Credentials Saved (all in ~/.zshrc — nothing to re-enter)
- `SENDGRID_API_KEY` — email sending
- `CRAIGSLIST_EMAIL` / `CRAIGSLIST_PASSWORD` — saved (not using)
- `INSTAGRAM_USERNAME` = WebByMaya
- `INSTAGRAM_PASSWORD` — saved
- Gmail read access authorized at `~/.webbymaaya/gmail_token.json`

---

## One Thing Left: Activate Instagram

The Instagram account exists and all scripts are ready. Just needs a one-time login to save the session.

### Step 1 — Finish the profile (instagram.com on desktop)
- [ ] Profile photo → upload `/Users/mayasierra/WebByMaya/public/icon-512.png`
- [ ] Bio:
  ```
  Philadelphia web designer 🌐
  Websites for local businesses
  $799 flat · live in 7 days
  Philly · South Jersey · Delaware
  ```
- [ ] Website → `webbymaya.com`

### Step 2 — Warm the account (2 minutes)
Browse Instagram for a few minutes after setting up the profile — follow a few local Philly accounts manually. Instagram blocks instant API logins on brand-new accounts.

### Step 3 — Fire first post + save session
```bash
cd ~/webbymaaya-scripts && python3 instagram_poster.py
```
This posts caption #1 and saves the login session. After this, Mon/Wed/Fri posting and daily following both run automatically.

---

## Current Pipeline Stats (as of June 9)
- Total emails sent (all time): **75**
- Unique inboxes hit: **55**
- Total SMS sent: **1,197**
- Follow-up emails sent today: **10**
- Zones completed: **7 / 23**
- Next zone: `sj-camden`
- Bounce rate: **13.3%**

---

## Logs & Files
| File | Purpose |
|---|---|
| `cron_run.log` | Daily pipeline output |
| `send_log_YYYY-MM-DD.csv` | Email send records |
| `sms_log_YYYY-MM-DD.csv` | SMS send records |
| `email_followup_log_YYYY-MM-DD.csv` | Follow-up email records |
| `bounce_log.csv` | Bounced/blocked emails (never retried) |
| `zone_state.json` | Zone rotation progress |
| `.seen_replies.json` | Tracks which Gmail replies you've already seen |
| `igfollow.log` | Instagram follow activity |
| `instagram.log` | Instagram post activity |

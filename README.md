# Indian Embassy Netherlands — Appointment Availability

[![Update Slots — Full](https://github.com/thatsuperdev/nl_ind_appointments/actions/workflows/update-slots-full.yml/badge.svg)](https://github.com/thatsuperdev/nl_ind_appointments/actions/workflows/update-slots-full.yml)
[![Update Slots — Quick](https://github.com/thatsuperdev/nl_ind_appointments/actions/workflows/update-slots-quick.yml/badge.svg)](https://github.com/thatsuperdev/nl_ind_appointments/actions/workflows/update-slots-quick.yml)

A public page showing available appointment slots at the Indian Embassy in The Hague, updated every 10 minutes during embassy hours.

**Live site:** deploy to Netlify (see setup below)  
**Data source:** [appointment.indianembassynetherland.com](https://appointment.indianembassynetherland.com/book_appointment)

---

## How it works

```
GitHub Actions cron
  ├─ Quick scan (every 10 min, Mon–Sat 08:00–16:00 Amsterdam)
  │    Checks next 14 days · ~14 API calls · merges with existing data
  └─ Full scan (every 2 hours)
       Checks current + next month · ~45 API calls · rebuilds completely
          ↓
       commits slots.json
          ↓
       Netlify auto-deploys (~30s)
          ↓
       index.html fetches fresh slots.json every 10 min
```

The Python script fetches a fresh CSRF token from the booking page on every run, so no manual token management is needed.

---

## Setup

### 1. Fork & connect to Netlify

1. Fork this repo
2. In [Netlify](https://netlify.com): **Add new site → Import from Git → pick your fork**
3. Build command: *(leave empty)*  
   Publish directory: `.`
4. Deploy — your site is live

### 2. Enable GitHub Actions write access

In your fork: **Settings → Actions → General → Workflow permissions → Read and write permissions**

This allows the cron job to commit updated `slots.json` back to the repo (which triggers a Netlify redeploy automatically).

### 3. Trigger the first run

Go to **Actions → Update Slots — Full → Run workflow** to populate `slots.json` with real data immediately, rather than waiting for the next scheduled run.

---

## Running locally

```bash
pip install -r requirements.txt

# Full scan (all weekdays, current + next 2 months)
python check_slots.py

# Quick scan (next 14 days only, for testing)
python check_slots.py --quick
```

Both modes write `slots.json` to the current directory and print a summary to the terminal. Open `index.html` in a browser (via a local server, not `file://`) to preview the page:

```bash
python -m http.server 3000
# then open http://localhost:3000
```

---

## File structure

| File | Purpose |
|------|---------|
| `index.html` | Static frontend — fetches and renders `slots.json` |
| `slots.json` | Generated data file — committed by CI, served by Netlify |
| `check_slots.py` | Scraper — fetches token, calls API in parallel, writes `slots.json` |
| `netlify.toml` | Cache-control headers — ensures `slots.json` is never served stale |
| `.github/workflows/update-slots-quick.yml` | 10-min cron for near-term freshness |
| `.github/workflows/update-slots-full.yml` | 2-hour cron for full date range |

---

## Disclaimer

This project is not affiliated with the Indian Embassy Netherlands. Always confirm availability on the [official booking site](https://appointment.indianembassynetherland.com/book_appointment) before travelling.

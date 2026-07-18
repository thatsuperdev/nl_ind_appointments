# Indian Embassy Netherlands — Appointment Availability

[![Update Slots — Full](https://github.com/thatsuperdev/nl_ind_appointments/actions/workflows/update-slots-full.yml/badge.svg)](https://github.com/thatsuperdev/nl_ind_appointments/actions/workflows/update-slots-full.yml)
[![Update Slots — Quick](https://github.com/thatsuperdev/nl_ind_appointments/actions/workflows/update-slots-quick.yml/badge.svg)](https://github.com/thatsuperdev/nl_ind_appointments/actions/workflows/update-slots-quick.yml)

A public page showing available appointment slots at the Indian Embassy in The Hague, updated every 10 minutes during embassy hours.

**Live site:** deploy to Netlify (see setup below)  
**Data source:** [appointment.indianembassynetherland.com](https://appointment.indianembassynetherland.com/)

---

## How it works

```
GitHub Actions cron
  ├─ Quick scan (every 15 min, plus 5-min bursts around Thu/1st release windows)
  │    Checks next 14 days · merges with existing data
  └─ Full scan (every 2 hours)
       Checks current + next month · rebuilds completely
          ↓
       writes slots.json to Netlify Blobs (netlify-cli, no git commit)
          ↓
       /.netlify/functions/appointment-data serves it (gated, see below)
          ↓
       index.html fetches it every 10 min
```

The Python script fetches a fresh CSRF token from the booking page on every run, so no manual token management is needed.

`slots.json` is **not** committed to git — it's gitignored, and there is no static `/slots.json` file in the deploy at all. The data lives in [Netlify Blobs](https://docs.netlify.com/build/data-and-storage/netlify-blobs/) and is served through a Netlify Function (`netlify/functions/appointment-data.mts`). This keeps the cron cadence (down to a few minutes, if needed) from spamming the git history or triggering a full Netlify rebuild on every run — Blob writes don't create commits or deploys.

**Access gating:** the function only serves data to requests whose `Origin`/`Referer` matches the site's own domain (i.e. loaded from `index.html`), or that carry the `x-freshness-check` secret header used by the watchdog. A bare `curl` or a browser hitting the function URL directly gets a 403. This is a soft gate, not real auth — headers can be spoofed by a determined caller — but it stops the feed from being casually scraped, indexed, or hotlinked outside the page.

> **Invariant:** don't add a static `slots.json` file back into the deployed root — if one exists, Netlify will serve it directly and bypass the function's gating entirely.

---

## Setup

### 1. Fork & connect to Netlify

1. Fork this repo
2. In [Netlify](https://netlify.com): **Add new site → Import from Git → pick your fork**
3. Build command: *(leave empty)*  
   Publish directory: `.`
4. Deploy — your site is live

### 2. Create a Netlify Blobs store and auth token

1. Grab your **Site ID**: Netlify site → **Project configuration → General → Project information → Project ID**
2. Create a **Personal Access Token**: Netlify **User settings → Applications → New access token**
3. In your fork: **Settings → Secrets and variables → Actions**, add:
   - `NETLIFY_SITE_ID` — the Site ID from step 1
   - `NETLIFY_AUTH_TOKEN` — the token from step 2

The workflows use these (via `netlify-cli`) to read/write the `slots-data` blob store directly — no GitHub write access to the repo is needed for this.

### 3. Set a freshness-watchdog secret

1. Pick any random string as a shared secret.
2. Add it as a GitHub Actions secret `FRESHNESS_WATCHDOG_SECRET`.
3. Add the *same* value as a Netlify **environment variable** (Site configuration → Environment variables) named `FRESHNESS_WATCHDOG_SECRET`, so the function can check it.

This lets the hourly `check-freshness.yml` watchdog read the data feed directly without opening it up to anyone else who just requests the URL.

### 4. Trigger the first run

Go to **Actions → Update Slots — Full → Run workflow** to populate the blob store with real data immediately, rather than waiting for the next scheduled run.

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
| `index.html` | Static frontend — fetches and renders the appointment data feed |
| `slots.json` | Generated data file (gitignored) — written locally, then pushed to Netlify Blobs |
| `check_slots.py` | Scraper — fetches token, calls API in parallel, writes `slots.json` |
| `netlify/functions/appointment-data.mts` | Serves the blob, gated by Origin/Referer + watchdog secret |
| `netlify.toml` | Cache-control headers so the data feed is never served stale |
| `.github/workflows/update-slots-quick.yml` | 15-min cron (with denser release-window bursts) for near-term freshness |
| `.github/workflows/update-slots-full.yml` | 2-hour cron for full date range |
| `.github/workflows/check-freshness.yml` | Hourly watchdog hitting the gated function with the shared secret |

---

## Disclaimer

This project is not affiliated with the Indian Embassy Netherlands. Always confirm availability on the [official booking site](https://appointment.indianembassynetherland.com/) before travelling.

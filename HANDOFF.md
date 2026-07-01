# LLM Handoff — Indian Embassy NL Appointment Checker

**Repo:** `github.com:thatsuperdev/nl_ind_appointments` (main branch)  
**Live site:** Netlify static hosting (auto-deploys on commit to main)  
**Last updated:** 2026-07-01

---

## What this project is

A public appointment slot checker for the Indian Embassy Netherlands booking site. Architecture:

```
Python scraper (check_slots.py)
  → GitHub Actions cron (quick: */10 min Mon–Sat, full: every 2h)
  → commits slots.json to repo
  → Netlify auto-deploys (~30s)
  → index.html fetches slots.json every 10 min
```

No backend. No database. Pure static.

---

## File map

| File | Purpose |
|------|---------|
| `index.html` | Static frontend — fetches and renders `slots.json` |
| `slots.json` | Generated data file — committed by CI, served by Netlify |
| `check_slots.py` | Scraper — fetches CSRF token, calls API in parallel, writes `slots.json` |
| `netlify.toml` | `Cache-Control: no-cache` on `slots.json` so it's never served stale |
| `.github/workflows/update-slots-quick.yml` | 10-min cron, next 14 days, merges into existing data |
| `.github/workflows/update-slots-full.yml` | 2-hour cron, current + next month, rebuilds from scratch |
| `requirements.txt` | Just `requests` |

---

## Embassy API — critical knowledge

**Booking page:** `https://appointment.indianembassynetherland.com/book_appointment`  
**Data API:** `POST https://appointment.indianembassynetherland.com/getBookingData`  
**POST body:** `appmnt_date=DD-MM-YYYY&_token=<csrf>`

### Session rate limiting (the core gotcha)
The embassy server invalidates its session after ~4 POST requests. If you reuse a session across multiple dates, only the first 3–4 return real data; all others return HTTP 405. **Every date must use a fresh session + fresh CSRF token.**

### Two different availability signals
The API response has two fields. They mean different things:

| Field | What it is | Reliable? |
|-------|-----------|-----------|
| `services` dict | Configured capacity quota per service (e.g., `"Passport Services (12 available)"`) | **NO** — shows quota even when all slots are booked |
| `timeslots_html` | HTML list of 30 time windows with `disabled="true"` on booked ones | **YES** — ground truth |

**Decision:** `slots_available` in `slots.json` stores `len(available_times)` (parsed from `timeslots_html`), NOT the services dict count. A date is only included if it has at least 1 non-disabled time window.

### Booking window
The embassy only opens slots for the current calendar month + next calendar month. September and beyond may return HTTP 200 with slots but those are unreleased placeholder data. Scraper is capped at `months_ahead=1` (= end of next calendar month).

### Embassy operating days
**Monday–Friday only.** Saturday and Sunday return HTTP 405. The scraper uses `weekday() < 5`.

### HTTP 405 meaning
- Date outside the bookable window → not an error, treated as "no availability"
- Session expired (>4 requests same session) → the old bug; now fixed by fresh-session-per-date

---

## check_slots.py — key decisions

### Fresh session per date
```python
def fetch_slot_data(appt_date: date) -> dict:
    session, token = fresh_session_and_token()  # new session every call
    resp = session.post(API_URL, data={"appmnt_date": date_str, "_token": token})
```
4 workers run in parallel. Each creates its own independent session. This is critical — sharing sessions causes silent failures.

### Availability gate (both paths)
```python
# Fresh data path (write_slots_json):
if count > 0 and r["available_times"]:   # <-- both conditions required
    kept.append({"slots_available": len(r["available_times"]), ...})

# Merge path (quick mode keeps old data for dates outside window):
if d["date"] not in fresh_dates and d.get("times"):  # <-- drop stale entries with no times
    kept.append(d)
```

### Quick vs full mode
- `--quick`: scans next 14 days, merges with existing slots.json (preserves future dates)
- default: scans current + next month, rebuilds from scratch (no merge)

---

## index.html — key decisions

### Time display
Times from slots.json are stored as `"1018 – 1026"`. The frontend formats them as `"10:18 – 10:26"` via:
```javascript
function formatTime(raw) {
  return raw.replace(/\b(\d{2})(\d{2})\b/g, '$1:$2');
}
```

### Card UI
- Grid: `repeat(auto-fill, minmax(190px, 1fr))` — 3 cols desktop, 2 mobile, 1 narrow
- Cards are accordion: click header → expand body with time chips
- Body shows time chips (warm gold styling) — no per-card disclaimer
- Book button in footer always visible, links to `data.booking_url` = `/book_appointment`

### Data contract (slots.json shape)
```json
{
  "generated_at": "<ISO timestamp>",
  "period_end": "31-08-2026",
  "booking_url": "https://appointment.indianembassynetherland.com/book_appointment",
  "services": {
    "1": {
      "name": "Passport Services",
      "dates": [
        {
          "date": "03-07-2026",
          "day": "Friday",
          "slots_available": 1,
          "times": ["10:18 – 10:26"]
        }
      ]
    }
  }
}
```
Note: `times` in slots.json are stored raw (`"1018 – 1026"`), formatted only in the frontend.

---

## Known limitations

1. **`slots_available` is time-window count, not per-service count.** All services on the same day share the same 30 time windows. If a day has 18 open windows, every service on that day shows "18 time slots." There's no API way to get per-service time slot breakdown.

2. **The `services` dict quota numbers are ignored** (they reflect configured capacity, not real bookings). Only `timeslots_html` is used.

3. **Slot count drops to near-zero once near-term dates fill up.** July weekdays are mostly booked. August starts opening mid-month. This is expected behavior.

---

## Things to be careful about

- **Don't reuse sessions across dates.** Will silently break things.
- **Don't go beyond months_ahead=1.** Embassy calendar doesn't reliably serve beyond next month.
- **Don't show Saturdays/Sundays.** Embassy closed.
- **Don't trust `services` dict counts as real-time availability.** They're misleading.
- **CI write permissions must be enabled** in GitHub Actions settings (`Settings → Actions → General → Workflow permissions → Read and write`).

---

## Possible next improvements

- Add last-known-good data fallback if scraper returns 0 results
- Per-service date count in the section subtitle (currently shows total unique dates)
- Push notification / Telegram bot when new slots open
- Track slot count history over time (currently stateless)

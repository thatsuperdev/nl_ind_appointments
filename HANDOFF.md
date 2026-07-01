# LLM Handoff — Indian Embassy NL Appointment Checker

**Repo:** `github.com:thatsuperdev/nl_ind_appointments` (main branch)  
**Live site:** Netlify static hosting (auto-deploys on commit to main)  
**Last updated:** 2026-07-01

---

## What this project is

A public appointment slot checker for the Indian Embassy Netherlands booking site. Architecture:

```
Python scraper (check_slots.py)
  → GitHub Actions cron (full-window: */10 min during embassy hours, fallback full every 2h)
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
| `.github/workflows/update-slots-quick.yml` | 10-min cron, current + next month, rebuilds from scratch |
| `.github/workflows/update-slots-full.yml` | 2-hour fallback cron, current + next month, rebuilds from scratch |
| `requirements.txt` | Just `requests` |

---

## Embassy API — critical knowledge

**Booking page:** `https://appointment.indianembassynetherland.com/book_appointment`  
**Data API:** `POST https://appointment.indianembassynetherland.com/getBookingData`  
**POST body:** `appmnt_date=DD-MM-YYYY&_token=<csrf>`

### Session rate limiting (the core gotcha)
The embassy server invalidates its session after ~4 POST requests. If you reuse a session across multiple dates, only the first 3–4 return real data; all others return HTTP 405. **Every date must use a fresh session + fresh CSRF token.**

### Availability signals
The booking form/API expose three signals. They mean different things:

| Field | What it is | Reliable? |
|-------|-----------|-----------|
| booking form `no_dates` | Dates the embassy datepicker marks red/unselectable | **YES — hard gate** |
| `services` dict | Current service-specific availability count (e.g., `"OCI Services (6 available)"`) | **YES for count** |
| `timeslots_html` | Shared date-level time windows with `disabled="true"` on booked windows | **YES for open windows, not per-service count** |

**Decision:** first exclude all booking form `no_dates`. Then `slots_available` in `slots.json` stores the service-specific `services` count. `times` stores the shared open time-window list from `timeslots_html`. A date is only included if it is not blocked, the service count is > 0, and the date has at least 1 open time window.

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

### Datepicker blocklist
`fetch_blocked_dates()` follows the same instruction-accept flow as the browser, loads the booking form, and parses `var no_dates = [...]`. These dates are excluded before calling/writing API data. Direct `getBookingData` can still return stale-looking data for dates the actual calendar blocks (e.g. July 03 and OCI Aug 24 on 2026-07-01), so the blocklist must be treated as authoritative.

### Availability gate (both paths)
```python
# Fresh data path (write_slots_json):
if count > 0 and r["available_times"]:   # <-- both conditions required
    kept.append({"slots_available": count, "times": r["available_times"], ...})
```

### Quick vs full mode
- Frequent workflow runs default full mode every 10 minutes during embassy hours.
- Default full mode scans current + next month and rebuilds from scratch (no merge).
- `--quick` still exists for manual local checks, but should not drive production data because merge-preserved future dates can go stale.

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
- Grid: 3 cols desktop, 2 mobile, 1 narrow
- Cards are static; no per-card booking CTA
- Header has one global `Book appointment` CTA
- Body shows max 5 time-window chips plus `+N more` expand control

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

1. **`times` is a shared date-level window list, not per-service assignment.** `slots_available` is service-specific count; the exact per-service time-window allocation is not exposed by the API.

2. **Slot count drops to near-zero once near-term dates fill up.** July weekdays are mostly booked. August starts opening mid-month. This is expected behavior.

---

## Things to be careful about

- **Don't reuse sessions across dates.** Will silently break things.
- **Don't go beyond months_ahead=1.** Embassy calendar doesn't reliably serve beyond next month.
- **Don't show Saturdays/Sundays.** Embassy closed.
- **Don't use `timeslots_html` length as a per-service slot count.** It is a shared date-level window list.
- **CI write permissions must be enabled** in GitHub Actions settings (`Settings → Actions → General → Workflow permissions → Read and write`).

---

## Possible next improvements

- Add last-known-good data fallback if scraper returns 0 results
- Per-service date count in the section subtitle (currently shows total unique dates)
- Push notification / Telegram bot when new slots open
- Track slot count history over time (currently stateless)

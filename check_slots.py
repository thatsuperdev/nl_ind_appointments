#!/usr/bin/env python3
# If `requests` is missing: pip install requests
"""
Indian Embassy Netherlands - Appointment Slot Checker
Fetches available slots for all services across current + next month.
"""

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone

import requests

BOOKING_URL = "https://appointment.indianembassynetherland.com/book_appointment"
API_URL = "https://appointment.indianembassynetherland.com/getBookingData"
SUBMIT_INSTRUCTION_URL = "https://appointment.indianembassynetherland.com/submitInstruction"

SERVICE_NAMES = {
    "1": "Passport Services",
    "2": "Visa Services",
    "3": "OCI Services",
    "4": "Surrender",
    "5": "Misc. Consular Services",
}



def parse_available_slots_v2(html: str) -> list[str]:
    """Return list of available time slot labels from timeslots_html."""
    available = []
    for item in re.split(r'<li\b', html):
        # The input tag has disabled="true" when closed; skip those
        input_tag = re.search(r'<input\b[^>]*/>', item)
        if not input_tag:
            continue
        if re.search(r'\bdisabled\b', input_tag.group(0)):
            continue
        id_match = re.search(r'\bid="([^"]+)"', input_tag.group(0))
        if id_match and "(Available)" in item:
            available.append(id_match.group(1))
    return available


def get_weekdays(months_ahead: int = 1, days_ahead: int | None = None) -> list[date]:
    """Return weekdays (Mon-Sat) from today.

    Pass days_ahead for a rolling window (quick mode), or months_ahead for the full range.
    months_ahead=1 covers current month + next month (embassy's booking window).
    """
    today = date.today()
    if days_ahead is not None:
        end_date = today + timedelta(days=days_ahead)
    else:
        end_month = today.month + months_ahead
        end_year = today.year + (end_month - 1) // 12
        end_month = ((end_month - 1) % 12) + 1
        end_date = (
            date(end_year, 12, 31)
            if end_month == 12
            else date(end_year, end_month + 1, 1) - timedelta(days=1)
        )

    days = []
    current = today
    while current <= end_date:
        if current.weekday() < 5:  # Mon–Fri only
            days.append(current)
        current += timedelta(days=1)
    return days


def ddmmyyyy_to_iso(value: str) -> str:
    try:
        return datetime.strptime(value, "%d-%m-%Y").date().isoformat()
    except ValueError:
        return ""


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": BOOKING_URL,
}

TOKEN_PATTERNS = [
    r'<meta[^>]+name=["\']csrf-token["\'][^>]+content=["\']([^"\']+)',
    r'<input[^>]+name=["\']_token["\'][^>]+value=["\']([^"\']+)',
    r'"_token"\s*:\s*"([^"]+)"',
]


def extract_csrf_token(html: str) -> str:
    for pat in TOKEN_PATTERNS:
        m = re.search(pat, html)
        if m:
            return m.group(1)
    raise RuntimeError("Could not extract CSRF token")


def extract_js_string_array(html: str, name: str) -> set[str]:
    match = re.search(rf"\bvar\s+{re.escape(name)}\s*=\s*(\[[^;]*\]);", html, re.S)
    if not match:
        raise RuntimeError(f"Could not extract {name} from booking form")
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def booking_form_html(session: requests.Session) -> str:
    """Return the actual appointment form HTML, accepting instructions if needed."""
    page = session.get(BOOKING_URL, timeout=15)
    page.raise_for_status()
    if 'id="Appointment"' in page.text and "getBookingData" in page.text:
        return page.text

    token = extract_csrf_token(page.text)
    agree_match = re.search(r'<input[^>]+name=["\']agree["\'][^>]+value=["\']([^"\']+)', page.text, re.S)
    if not agree_match:
        raise RuntimeError("Could not extract instruction agreement value")

    form = session.post(
        SUBMIT_INSTRUCTION_URL,
        data={"_token": token, "agree": agree_match.group(1)},
        timeout=15,
    )
    form.raise_for_status()
    if 'id="Appointment"' not in form.text:
        raise RuntimeError("Instruction submit did not return booking form")
    return form.text


def fresh_session_and_token() -> tuple[requests.Session, str]:
    """Create a new session, load the booking form, and extract a fresh CSRF token."""
    session = requests.Session()
    session.headers.update(HEADERS)
    form_html = booking_form_html(session)
    return session, extract_csrf_token(form_html)


def fetch_blocked_dates() -> set[str]:
    """Return yyyy-mm-dd dates blocked by the embassy datepicker."""
    session = requests.Session()
    session.headers.update(HEADERS)
    form_html = booking_form_html(session)
    return extract_js_string_array(form_html, "no_dates")


def fetch_slot_data(appt_date: date) -> dict:
    """Fetch slot data for a single date using a fresh session per call.

    The embassy server invalidates its session after a handful of requests,
    so each date must start with its own fresh session + CSRF token.
    """
    date_str = appt_date.strftime("%d-%m-%Y")
    last_err = ""
    for attempt in range(3):
        try:
            session, token = fresh_session_and_token()
            resp = session.post(
                API_URL,
                data={"appmnt_date": date_str, "_token": token},
                timeout=15,
            )
            if resp.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            if resp.status_code == 405:
                # Date outside the bookable window — not an error, just no availability
                return {
                    "date": appt_date,
                    "date_str": date_str,
                    "available_times": [],
                    "services": {},
                    "error": None,
                }
            resp.raise_for_status()
            data = resp.json()
            available_times = parse_available_slots_v2(data.get("timeslots_html", ""))
            services_raw = data.get("services", {})
            services = {}
            for k, v in services_raw.items():
                count_match = re.search(r'\((\d+) available\)', v)
                name_match = re.match(r'^(.+?)\s*\(', v)
                if name_match:
                    name = name_match.group(1).strip()
                    count = int(count_match.group(1)) if count_match else 0
                    services[k] = {"name": name, "available": count}
            return {
                "date": appt_date,
                "date_str": date_str,
                "available_times": available_times,
                "services": services,
                "error": None,
            }
        except Exception as e:
            last_err = str(e)
            if attempt < 2:
                time.sleep(1)
    return {
        "date": appt_date,
        "date_str": date_str,
        "available_times": [],
        "services": {},
        "error": last_err,
    }


def main():
    quick = "--quick" in sys.argv
    mode_label = "QUICK (next 14 days)" if quick else "FULL (current + next month)"
    print(f"Indian Embassy Netherlands — Appointment Slot Checker [{mode_label}]")
    print("=" * 60)

    # Verify connectivity and mirror the booking form's blocked-date calendar.
    print("\nVerifying connectivity to booking site...", end=" ", flush=True)
    try:
        blocked_dates = fetch_blocked_dates()
        _, sample_token = fresh_session_and_token()
        print(f"OK (token: {sample_token[:12]}..., blocked dates: {len(blocked_dates)})")
    except Exception as e:
        print(f"FAILED\n{e}")
        sys.exit(1)

    # Step 2: Get list of weekdays to check
    all_weekdays = get_weekdays(days_ahead=14) if quick else get_weekdays(months_ahead=1)
    weekdays = all_weekdays
    print(f"Checking {len(weekdays)} weekdays from {weekdays[0]} to {weekdays[-1]}...")
    blocked_in_window = sum(1 for d in weekdays if d.isoformat() in blocked_dates)
    if blocked_in_window:
        print(f"{blocked_in_window} dates are disabled in the datepicker; checking API anyway.")
    print("(Each date uses a fresh session — server rate-limits shared sessions after ~4 requests)")

    # Step 3: Fetch all dates in parallel — each worker self-creates its own session
    results = []
    errors = 0
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(fetch_slot_data, d): d
            for d in weekdays
        }
        done = 0
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            done += 1
            if result["error"]:
                errors += 1
            print(f"\r  Progress: {done}/{len(weekdays)} dates checked", end="", flush=True)

    if errors:
        print(f"\n  Done with {errors}/{len(weekdays)} errors.")
    else:
        print("\n  Done.")

    if errors == len(weekdays):
        print("All requests failed — not writing slots.json to avoid overwriting good data.")
        sys.exit(1)

    # Step 4: Sort results by date
    results.sort(key=lambda r: r["date"])

    # Step 5: Collect all service keys seen
    all_services: set[str] = set()
    for r in results:
        all_services.update(r["services"].keys())

    # Step 6: Print terminal summary
    print()
    for svc_id in sorted(all_services, key=lambda x: int(x)):
        svc_name = SERVICE_NAMES.get(svc_id, f"Service {svc_id}")
        print(f"\n{'─' * 55}")
        print(f"  {svc_name}")
        print(f"{'─' * 55}")
        has_any = False
        for r in results:
            svc_data = r["services"].get(svc_id, {})
            count = svc_data.get("available", 0)
            if count > 0 and r["available_times"]:
                has_any = True
                day_name = r["date"].strftime("%a")
                times = ", ".join(r["available_times"][:6])
                suffix = f" +{len(r['available_times']) - 6} more" if len(r["available_times"]) > 6 else ""
                print(f"  {r['date_str']} ({day_name})  [{count:2d} slots]  {times}{suffix}")
        if not has_any:
            print("  No available slots found in this period.")

    # Step 7: Write slots.json for the hosted page
    json_path = "slots.json"
    write_slots_json(results, all_services, json_path, merge=quick, blocked_dates=blocked_dates)
    print(f"\n\nData saved to: {json_path}")


def write_slots_json(
    results: list,
    all_services: set,
    path: str,
    merge: bool = False,
    blocked_dates: set[str] | None = None,
):
    blocked_dates = blocked_dates or set()
    today = date.today()
    # In merge mode, load existing data so full-range dates are preserved
    existing = {}
    if merge:
        try:
            with open(path, encoding="utf-8") as f:
                existing = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    # Build a date→result map from the fresh fetch
    fresh_dates = {r["date_str"] for r in results}

    # Union of service IDs seen in fresh results + existing data
    all_known = set(all_services) | set(existing.get("services", {}).keys())

    services_out = {}
    for svc_id in sorted(all_known, key=lambda x: int(x)):
        svc_name = SERVICE_NAMES.get(svc_id, f"Service {svc_id}")

        # Start from existing dates outside the freshly-fetched window.
        # Only keep entries that had actual open time slots (d["times"] non-empty) —
        # this retroactively purges stale entries from before the availability gate fix.
        kept = []
        if merge:
            for d in existing.get("services", {}).get(svc_id, {}).get("dates", []):
                date_key = ddmmyyyy_to_iso(d.get("date", ""))
                if not date_key:
                    continue
                appt_date = date.fromisoformat(date_key)
                if (
                    appt_date >= today
                    and d["date"] not in fresh_dates
                    and d.get("times")
                ):
                    kept.append(d)

        # Add fresh results for the window we just checked.
        # Keep the service-specific count as slots_available. timeslots_html is
        # the shared appointment-window list for the date, not a per-service count.
        for r in results:
            svc_data = r["services"].get(svc_id, {})
            count = svc_data.get("available", 0)
            if count > 0 and r["available_times"]:
                kept.append({
                    "date": r["date_str"],
                    "day": r["date"].strftime("%A"),
                    "slots_available": count,
                    "times": r["available_times"],
                })

        # Sort by date, drop any entries with unparseable dates
        def _date_key(d):
            try:
                return datetime.strptime(d["date"], "%d-%m-%Y")
            except (KeyError, ValueError):
                return datetime.min

        kept.sort(key=_date_key)
        services_out[svc_id] = {"name": svc_name, "dates": kept}

    all_results = results or []
    period_end = existing.get("period_end", "") if merge else (all_results[-1]["date_str"] if all_results else "")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period_end": period_end,
        "booking_url": BOOKING_URL,
        "services": services_out,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


if __name__ == "__main__":
    main()

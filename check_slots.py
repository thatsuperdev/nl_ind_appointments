#!/usr/bin/env python3
# If `requests` is missing: pip install requests
"""
Indian Embassy Netherlands - Appointment Slot Checker
Fetches available slots for all services across current + next month.
"""

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone

import requests

BOOKING_URL = "https://appointment.indianembassynetherlands.com/book_appointment"
API_URL = "https://appointment.indianembassynetherlands.com/getBookingData"

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


def get_weekdays(months_ahead: int = 2) -> list[date]:
    """Return all weekdays (Mon-Sat) from today through N months ahead."""
    today = date.today()
    # Go to end of next month
    end_month = today.month + months_ahead
    end_year = today.year + (end_month - 1) // 12
    end_month = ((end_month - 1) % 12) + 1
    # Last day of that month
    if end_month == 12:
        end_date = date(end_year, 12, 31)
    else:
        end_date = date(end_year, end_month + 1, 1) - timedelta(days=1)

    days = []
    current = today
    while current <= end_date:
        # Monday=0 ... Saturday=5, Sunday=6
        if current.weekday() < 6:  # exclude Sunday
            days.append(current)
        current += timedelta(days=1)
    return days


def fetch_slot_data(session: requests.Session, token: str, appt_date: date) -> dict:
    """Call the API for a single date and return parsed result."""
    date_str = appt_date.strftime("%d-%m-%Y")
    try:
        resp = session.post(
            API_URL,
            data={"appmnt_date": date_str, "_token": token},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        available_times = parse_available_slots_v2(data.get("timeslots_html", ""))
        services_raw = data.get("services", {})
        # Parse "Passport Services (12 available)" -> count
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
        return {
            "date": appt_date,
            "date_str": date_str,
            "available_times": [],
            "services": {},
            "error": str(e),
        }


def main():
    print("Indian Embassy Netherlands — Appointment Slot Checker")
    print("=" * 55)

    # Step 1: Get a session and CSRF token
    print("\nFetching booking page to get session token...", end=" ", flush=True)
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": BOOKING_URL,
    })

    try:
        page = session.get(BOOKING_URL, timeout=15)
        page.raise_for_status()
    except Exception as e:
        print(f"FAILED\nCould not load booking page: {e}")
        sys.exit(1)

    # Extract CSRF token from meta tag or hidden input
    token_match = re.search(
        r'<meta\s+name=["\']csrf-token["\']\s+content=["\']([^"\']+)["\']', page.text
    ) or re.search(
        r'<input[^>]+name=["\']_token["\'][^>]+value=["\']([^"\']+)["\']', page.text
    ) or re.search(
        r'"_token"\s*:\s*"([^"]+)"', page.text
    )

    if not token_match:
        print("FAILED\nCould not find CSRF token in page. The site may have changed.")
        sys.exit(1)

    token = token_match.group(1)
    print(f"OK (token: {token[:12]}...)")

    # Step 2: Get list of weekdays to check
    weekdays = get_weekdays(months_ahead=2)
    print(f"Checking {len(weekdays)} weekdays from {weekdays[0]} to {weekdays[-1]}...")

    # Step 3: Fetch all dates in parallel
    results = []
    errors = 0
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(fetch_slot_data, session, token, d): d
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

    print(f"\n  Done. {errors} errors." if errors else "\n  Done.")

    # Step 4: Sort results by date
    results.sort(key=lambda r: r["date"])

    # Step 5: Collect all service keys seen
    all_services = set()
    for r in results:
        all_services.update(r["services"].keys())
    all_services = sorted(all_services, key=lambda x: int(x))

    # Step 6: Print terminal summary
    print()
    for svc_id in all_services:
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
    write_slots_json(results, all_services, json_path)
    print(f"\n\nData saved to: {json_path}")


def write_slots_json(results: list, all_services: set, path: str):

    services_out = {}
    for svc_id in sorted(all_services, key=lambda x: int(x)):
        svc_name = SERVICE_NAMES.get(svc_id, f"Service {svc_id}")
        dates = []
        for r in results:
            svc_data = r["services"].get(svc_id, {})
            count = svc_data.get("available", 0)
            if count > 0:
                dates.append({
                    "date": r["date_str"],
                    "day": r["date"].strftime("%A"),
                    "slots_available": count,
                    "times": r["available_times"],
                })
        services_out[svc_id] = {"name": svc_name, "dates": dates}

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period_end": results[-1]["date_str"] if results else "",
        "booking_url": BOOKING_URL,
        "services": services_out,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


if __name__ == "__main__":
    main()

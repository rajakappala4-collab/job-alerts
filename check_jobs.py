import requests
import json
import os
from datetime import datetime, timezone, timedelta

# ---- CONFIG ----
NTFY_TOPIC = "rajakappala-jobs-8823"
KEYWORDS = ["software engineer", "software developer", "sde", "backend", "full stack", "frontend", "swe"]
SEEN_FILE = "seen_jobs.json"
FRESHNESS_HOURS = 1  # only notify for jobs posted within this many hours

AMAZON_URL = "https://www.amazon.jobs/en/search.json?base_query=software+engineer&result_limit=20&sort=recent"

GREENHOUSE_COMPANIES = [
    "stripe", "airbnb", "coinbase", "reddit", "doordash", "robinhood",
    "pinterest", "databricks", "notion", "figma", "discord", "instacart",
    "lyft", "dropbox", "asana", "twitch", "peloton", "snowflake",
    "gitlab", "squarespace", "affirm", "plaid", "cloudflare", "roblox",
    "compass", "carta", "rippling", "webflow", "brex"
]

# Workday-based companies: (display_name, tenant, dc, site)
WORKDAY_COMPANIES = [
    ("Nvidia", "nvidia", "wd5", "NVIDIAExternalCareerSite"),
]

# Companies without a usable public API - manual check links only
MANUAL_CHECK_COMPANIES = {
    "Google": "https://www.google.com/about/careers/applications/jobs/results/?q=software%20engineer",
    "Meta": "https://www.metacareers.com/jobs/?q=software%20engineer",
    "Apple": "https://jobs.apple.com/en-us/search?search=software%20engineer",
    "Starbucks": "https://www.starbucks.com/careers/",
}


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)


def matches_keywords(title):
    title_lower = title.lower()
    return any(kw in title_lower for kw in KEYWORDS)


def is_fresh(timestamp_str, hours=FRESHNESS_HOURS):
    """Returns True if the ISO timestamp is within the last `hours` hours. If no
    timestamp is available, returns True (can't filter, so don't block it)."""
    if not timestamp_str:
        return True
    try:
        posted_time = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return (now - posted_time) <= timedelta(hours=hours)
    except Exception:
        return True


_notify_failure_count = 0
_notify_disabled = False


def notify(company, title, url, posted_str=None):
    global _notify_failure_count, _notify_disabled

    if _notify_disabled:
        print(f"Skipping notify (network appears down this run): {company}: {title}")
        return

    message = f"{company}: {title}"
    if posted_str:
        message += f" (posted {posted_str})"
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={"Click": url} if url else {},
            timeout=5
        )
        print(f"Notified: {message}")
        _notify_failure_count = 0
    except Exception as e:
        _notify_failure_count += 1
        print(f"Notify failed ({_notify_failure_count}/3): {e}")
        if _notify_failure_count >= 3:
            _notify_disabled = True
            print("3 notifications failed in a row - assuming network issue, skipping remaining notifications for this run.")


def check_amazon(seen):
    # Note: Amazon's feed gives day-level dates, not exact hours, so freshness
    # filtering here is approximate (same-day), not strictly "under 1 hour".
    try:
        resp = requests.get(AMAZON_URL, timeout=15)
        data = resp.json()
        today_str = datetime.now(timezone.utc).strftime("%B %d, %Y")
        for job in data.get("jobs", []):
            job_id = "amazon-" + str(job.get("id_icims", job.get("job_path", "")))
            title = job.get("title", "")
            posted_date = job.get("posted_date", "")
            if job_id and job_id not in seen and matches_keywords(title):
                if posted_date == today_str:
                    job_url = "https://www.amazon.jobs" + job.get("job_path", "")
                    notify("Amazon", title, job_url, posted_date)
                seen.add(job_id)
    except Exception as e:
        print(f"Amazon check failed: {e}")


def check_greenhouse(company_name, seen):
    url = f"https://api.greenhouse.io/v1/boards/{company_name}/jobs"
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
            print(f"{company_name}: no data (status {resp.status_code})")
            return
        data = resp.json()
        for job in data.get("jobs", []):
            job_id = f"{company_name}-" + str(job.get("id", ""))
            title = job.get("title", "")
            first_published = job.get("first_published", "")
            if job_id and job_id not in seen and matches_keywords(title):
                if is_fresh(first_published):
                    job_url = job.get("absolute_url", "")
                    notify(company_name.capitalize(), title, job_url, first_published)
                seen.add(job_id)
    except Exception as e:
        print(f"{company_name} check failed: {e}")


def check_workday(display_name, tenant, dc, site, seen):
    url = f"https://{tenant}.{dc}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    body = {
        "appliedFacets": {},
        "limit": 20,
        "offset": 0,
        "searchText": "software engineer"
    }
    try:
        resp = requests.post(url, json=body, timeout=15)
        if resp.status_code != 200:
            print(f"{display_name} (Workday): no data (status {resp.status_code})")
            return
        data = resp.json()
        for job in data.get("jobPostings", []):
            title = job.get("title", "")
            job_path = job.get("externalPath", "")
            job_id = f"{display_name}-" + job_path
            posted_on = job.get("postedOn", "")  # e.g. "Posted Today", "Posted 3 Days Ago"
            if job_id and job_id not in seen and matches_keywords(title):
                # Workday gives relative text, not a precise timestamp -
                # only auto-notify for "Posted Today" as the closest fit
                if "today" in posted_on.lower() or posted_on == "":
                    job_url = f"https://{tenant}.{dc}.myworkdayjobs.com/{site}{job_path}"
                    notify(display_name, title, job_url, posted_on)
                seen.add(job_id)
    except Exception as e:
        print(f"{display_name} (Workday) check failed: {e}")


def send_manual_check_reminder(seen):
    reminder_id = "manual-check-reminder-v1"
    if reminder_id in seen:
        return
    links = "\n".join([f"{name}: {url}" for name, url in MANUAL_CHECK_COMPANIES.items()])
    message = f"Manual check needed (no auto-feed available):\n{links}"
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            timeout=10
        )
        seen.add(reminder_id)
        print("Sent manual check reminder")
    except Exception as e:
        print(f"Manual reminder failed: {e}")


def main():
    seen = load_seen()

    check_amazon(seen)

    for company in GREENHOUSE_COMPANIES:
        check_greenhouse(company, seen)

    for display_name, tenant, dc, site in WORKDAY_COMPANIES:
        check_workday(display_name, tenant, dc, site, seen)

    send_manual_check_reminder(seen)

    save_seen(seen)


if __name__ == "__main__":
    main()

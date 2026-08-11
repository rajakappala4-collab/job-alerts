import requests
import json
import os

# ---- CONFIG ----
NTFY_TOPIC = "rajakappala-jobs-8823"
KEYWORDS = ["software engineer", "software developer", "sde", "backend", "full stack", "frontend", "swe"]
SEEN_FILE = "seen_jobs.json"

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


def notify(company, title, url):
    message = f"{company}: {title}"
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={"Click": url} if url else {},
            timeout=10
        )
        print(f"Notified: {message}")
    except Exception as e:
        print(f"Notify failed: {e}")


def check_amazon(seen):
    try:
        resp = requests.get(AMAZON_URL, timeout=15)
        data = resp.json()
        for job in data.get("jobs", []):
            job_id = "amazon-" + str(job.get("id_icims", job.get("job_path", "")))
            title = job.get("title", "")
            if job_id and job_id not in seen and matches_keywords(title):
                job_url = "https://www.amazon.jobs" + job.get("job_path", "")
                notify("Amazon", title, job_url)
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
            if job_id and job_id not in seen and matches_keywords(title):
                job_url = job.get("absolute_url", "")
                notify(company_name.capitalize(), title, job_url)
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
            if job_id and job_id not in seen and matches_keywords(title):
                job_url = f"https://{tenant}.{dc}.myworkdayjobs.com/{site}{job_path}"
                notify(display_name, title, job_url)
                seen.add(job_id)
    except Exception as e:
        print(f"{display_name} (Workday) check failed: {e}")


def send_manual_check_reminder(seen):
    # Sends the manual-check links once (marked as seen so it doesn't repeat every run)
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

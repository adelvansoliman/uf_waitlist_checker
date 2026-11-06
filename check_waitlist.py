"""Read-only UF course waitlist monitor with optional Discord notifications.

Run on Windows, macOS, or Linux:
    python check_waitlist.py --test
    python check_waitlist.py --once
    python check_waitlist.py
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

API_URL = "https://one.uf.edu/apix/soc/schedule/"
ONE_UF_URL = "https://one.uf.edu/"
DEFAULT_STATE_FILE = ROOT / ".state" / "notified.json"
LOG = logging.getLogger("uf_waitlist")


@dataclass(frozen=True)
class Config:
    webhook_url: str
    term: str
    category: str
    course_codes: tuple[str, ...]
    class_numbers: frozenset[str]
    interval_seconds: int
    state_file: Path = DEFAULT_STATE_FILE


def comma_separated(value: str) -> tuple[str, ...]:
    return tuple(piece.strip() for piece in value.split(",") if piece.strip())


def load_config(interval_override: int | None = None) -> Config:
    codes = tuple(dict.fromkeys(s.upper() for s in comma_separated(
        os.getenv("COURSE_CODES", "EEL4712C")
    )))
    if not codes:
        raise ValueError("COURSE_CODES must include at least one course code.")

    interval = (interval_override if interval_override is not None
                else int(os.getenv("CHECK_INTERVAL_SECONDS", "1800")))
    if interval < 60:
        raise ValueError("CHECK_INTERVAL_SECONDS must be at least 60 seconds.")

    return Config(
        webhook_url=os.getenv("DISCORD_WEBHOOK_URL", "").strip(),
        term=os.getenv("TERM", "2271").strip(),
        category=os.getenv("CATEGORY", "CWSP").strip(),
        course_codes=codes,
        class_numbers=frozenset(comma_separated(os.getenv("CLASS_NUMBERS", ""))),
        interval_seconds=interval,
    )


def validate_webhook(url: str) -> None:
    """Avoid accidentally starting a monitor with a missing webhook."""
    parsed = urlparse(url)
    if (parsed.scheme != "https"
            or parsed.hostname not in {"discord.com", "discordapp.com"}
            or not re.fullmatch(r"/api/webhooks/\d+/[^/\s]+", parsed.path)
            or "REPLACE" in url.upper()):
        raise ValueError(
            "Set a valid DISCORD_WEBHOOK_URL in .env (Discord channel -> Integrations -> Webhooks)."
        )


def create_session() -> requests.Session:
    session = requests.Session()
    # Only retry GET requests, never Discord POSTs (avoids duplicate messages).
    retry = Retry(
        total=2,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET"]),
        respect_retry_after_header=True,
    )
    session.mount("https://one.uf.edu/", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": "UF-Waitlist-Monitor/1.0 (personal read-only monitor)"})
    return session


def fetch_sections(session: requests.Session, course_code: str, config: Config) -> list[dict]:
    """Request public course data and keep only the exact course-code match."""
    response = session.get(
        API_URL,
        params={
            "category": config.category,
            "term": config.term,
            "course-code": course_code,
            "last-control-number": 0,
        },
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        raise ValueError("Unexpected UF API response format.")

    courses = payload[0].get("COURSES")
    if not isinstance(courses, list):
        raise ValueError("UF API response did not contain a COURSES list.")

    sections: list[dict] = []
    for course in courses:
        if course.get("code", "").upper() == course_code.upper():
            sections.extend(course.get("sections") or [])
    return sections


def waitlist_openings(section: dict) -> tuple[int | None, int | None, int | None, str]:
    """Return (spots, total, capacity, eligibility_flag).

    'isEligible' is not necessarily a user's personal prerequisite eligibility.
    We intentionally alert when total < capacity even if the flag is 'N'.
    An API count does NOT guarantee ONE.UF will allow joining.
    """
    wl = section.get("waitList") or {}
    total, capacity = wl.get("total"), wl.get("cap")
    flag = str(wl.get("isEligible", "?"))
    if (type(total) is not int or type(capacity) is not int
            or capacity <= 0 or not 0 <= total <= capacity):
        return None, total, capacity, flag
    return capacity - total, total, capacity, flag


def read_notified(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        values = data["notified"]
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            raise ValueError("Invalid notified state")
        return set(values)
    except (OSError, ValueError, KeyError) as exc:
        LOG.warning("Could not read notification state (%s); using empty state.", exc)
        return set()


def write_notified(path: Path, values: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps({"notified": sorted(values)}, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def send_discord(webhook_url: str, message: str) -> None:
    # wait=true means Discord confirms that it saved the message.
    response = requests.post(
        webhook_url,
        params={"wait": "true"},
        json={
            "content": message,
            "username": "UF Waitlist Monitor",
            "allowed_mentions": {"parse": []},
        },
        timeout=15,
    )
    response.raise_for_status()


def safe_discord_error(exc: requests.RequestException) -> str:
    """Avoid leaking the secret webhook token through request exception URLs."""
    response = getattr(exc, "response", None)
    if response is not None:
        return f"{type(exc).__name__} (HTTP {response.status_code})"
    return f"{type(exc).__name__} (check webhook URL and network connection)"


def alert_message(course_code: str, section: dict, total: int, capacity: int, flag: str) -> str:
    class_number = section["classNumber"]
    section_number = section.get("number", "?")
    spots = capacity - total
    return (
        "🚨 **Possible UF waitlist opening**\n"
        f"**Course:** {course_code}\n"
        f"**Class #:** {class_number} (section {section_number})\n"
        f"**Waitlist:** {total}/{capacity} — {spots} possible spot(s)\n"
        f"**API eligibility flag:** {flag}\n\n"
        f"Check ONE.UF manually: {ONE_UF_URL}\n"
        "The public API count may be delayed; joining is not guaranteed."
    )


def check_once(config: Config, session: requests.Session, notified: set[str]) -> bool:
    """Check each requested course; return True if no request/notification failed."""
    all_ok = True
    changed = False

    for code in config.course_codes:
        try:
            sections = fetch_sections(session, code, config)
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            LOG.error("Could not check %s: %s", code, exc)
            all_ok = False
            continue

        selected = [s for s in sections
                    if not config.class_numbers or str(s.get("classNumber", "")) in config.class_numbers]
        if not selected:
            LOG.warning("No matching sections found for %s. Check COURSE_CODES and CLASS_NUMBERS.", code)
            all_ok = False
            continue

        for section in selected:
            class_number = section.get("classNumber")
            if class_number is None:
                LOG.warning("Skipping section with missing classNumber for %s", code)
                all_ok = False
                continue

            key = f"{code}:{class_number}"
            spots, total, capacity, flag = waitlist_openings(section)
            LOG.info("%s class %s (section %s): waitlist %s/%s, eligible flag %s",
                     code, class_number, section.get("number", "?"), total, capacity, flag)

            if spots is None:
                LOG.warning("Unknown/inconsistent waitlist numbers for %s; no alert.", key)
                continue
            if spots == 0:
                if key in notified:
                    notified.remove(key)
                    changed = True
                continue

            if key in notified:
                continue  # Already notified while this section remains open.

            try:
                send_discord(config.webhook_url, alert_message(code, section, total, capacity, flag))
            except requests.RequestException as exc:
                LOG.error("Discord notification failed for %s: %s", key, safe_discord_error(exc))
                all_ok = False
                continue  # Don't mark notified; allow retry next check.

            LOG.info("Discord alert sent for %s (%d potential spot(s)).", key, spots)
            notified.add(key)
            changed = True

    if changed:
        try:
            write_notified(config.state_file, notified)
        except OSError as exc:
            LOG.error("Could not save notification state: %s", exc)
            all_ok = False
    return all_ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only UF waitlist monitor with Discord alerts")
    parser.add_argument("--test", action="store_true", help="Send a Discord test message, no UF request")
    parser.add_argument("--once", action="store_true", help="Check the UF waitlist once and exit")
    parser.add_argument("--interval", type=int, help="Override check interval in seconds (min 60)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    try:
        config = load_config(args.interval)
        validate_webhook(config.webhook_url)
    except ValueError as exc:
        LOG.error("Configuration error: %s", exc)
        return 2

    if args.test:
        try:
            send_discord(config.webhook_url, "✅ **UF Waitlist Monitor Test**\nDiscord notifications are working!")
            LOG.info("Discord test sent successfully.")
            return 0
        except requests.RequestException as exc:
            LOG.error("Discord test failed: %s", safe_discord_error(exc))
            return 1

    notified = read_notified(config.state_file)
    session = create_session()

    try:
        while True:
            LOG.info("Checking ONE.UF for: %s", ", ".join(config.course_codes))
            success = check_once(config, session, notified)
            if args.once:
                return 0 if success else 1
            LOG.info("Next check in %d minutes.", config.interval_seconds // 60)
            time.sleep(config.interval_seconds)
    except KeyboardInterrupt:
        LOG.info("Stopped by user.")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())

"""
Posts a daily tweet listing active NBA players whose birthday it is today,
using US Eastern Time as the reference date (matching how the NBA schedules
games — see the main site's app.js for the same convention).

GitHub's `schedule:` trigger is unreliable for a single once-a-day cron tick
(it can be delayed by hours on lower-traffic repos), so this is designed to
be invoked every 15 minutes instead. It only actually posts once it's the
target hour in US Eastern time, and only once per day (tracked via
last_posted.txt, committed back to the repo by the workflow) — every other
invocation exits immediately without calling any API.

Required environment variables (set as GitHub Actions secrets):
    X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET

Set DRY_RUN=1 to print the tweet instead of posting it (no credentials
needed in that mode) — useful for testing the data/formatting locally.

A manual run (GITHUB_EVENT_NAME=workflow_dispatch, or no GITHUB_EVENT_NAME at
all, i.e. running locally) always bypasses both the target-hour check and the
already-posted-today check, so testing isn't blocked by either gate.
"""

import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

TARGET_HOUR_ET = 18  # 6pm ET — checked every 15 min, so any tick in this hour posts
STATE_FILE = Path(__file__).parent / "last_posted.txt"

TEAM_IDS = {
    1: "Atlanta Hawks", 2: "Boston Celtics", 17: "Brooklyn Nets", 30: "Charlotte Hornets",
    4: "Chicago Bulls", 5: "Cleveland Cavaliers", 6: "Dallas Mavericks", 7: "Denver Nuggets",
    8: "Detroit Pistons", 9: "Golden State Warriors", 10: "Houston Rockets", 11: "Indiana Pacers",
    12: "LA Clippers", 13: "Los Angeles Lakers", 29: "Memphis Grizzlies", 14: "Miami Heat",
    15: "Milwaukee Bucks", 16: "Minnesota Timberwolves", 3: "New Orleans Pelicans", 18: "New York Knicks",
    25: "Oklahoma City Thunder", 19: "Orlando Magic", 20: "Philadelphia 76ers", 21: "Phoenix Suns",
    22: "Portland Trail Blazers", 23: "Sacramento Kings", 24: "San Antonio Spurs", 28: "Toronto Raptors",
    26: "Utah Jazz", 27: "Washington Wizards",
}

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

TWEET_MAX_LEN = 280


def fetch_active_players():
    players = []
    for team_id, team_name in TEAM_IDS.items():
        url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}/roster"
        resp = requests.get(url, headers={"User-Agent": "nba-birthday-bot/1.0"}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        for athlete in data.get("athletes", []):
            dob = athlete.get("dateOfBirth")
            if not dob:
                continue
            year, month, day = (int(x) for x in dob[:10].split("-"))
            players.append({
                "name": athlete.get("fullName") or athlete.get("displayName"),
                "team": team_name,
                "month": month,
                "day": day,
                "year": year,
            })
    return players


def get_us_now():
    return datetime.now(ZoneInfo("America/New_York"))


def is_manual_run():
    # Defaults to True (bypass gates) when GITHUB_EVENT_NAME is unset, which
    # covers running the script locally for testing.
    return os.environ.get("GITHUB_EVENT_NAME", "workflow_dispatch") == "workflow_dispatch"


def already_posted_today(today_str):
    if not STATE_FILE.exists():
        return False
    return STATE_FILE.read_text().strip() == today_str


def mark_posted_today(today_str):
    STATE_FILE.write_text(today_str + "\n")


def build_tweet(todays_players, month, day):
    date_str = f"{MONTH_NAMES[month - 1]} {day}"
    header = f"\U0001F3C0\U0001F382 NBA birthdays today ({date_str}, US ET):"
    lines = [f"- {p['name']} ({p['team']})" for p in todays_players]
    player_block = header + "\n\n" + "\n".join(lines)

    prop_word = "props" if len(todays_players) > 1 else "prop"
    hook = f"Will they hit the over on their points {prop_word}?"
    cta = "Track other birthdays for sports betting - link in bio"
    footer = hook + "\n\n" + cta

    full = player_block + "\n\n" + footer
    if len(full) <= TWEET_MAX_LEN:
        return full

    # Footer (hook + CTA) doesn't fit — drop it before ever truncating the
    # player list, since the list is the actual content.
    if len(player_block) <= TWEET_MAX_LEN:
        return player_block

    # Still too long even without the footer (many players share a
    # birthday) — truncate the list and note how many more.
    kept = []
    for line in lines:
        remaining = len(lines) - len(kept) - 1
        suffix = f"\n+{remaining} more" if remaining > 0 else ""
        candidate = header + "\n\n" + "\n".join(kept + [line]) + suffix
        if len(candidate) > TWEET_MAX_LEN:
            break
        kept.append(line)
    remaining = len(lines) - len(kept)
    suffix = f"\n+{remaining} more" if remaining > 0 else ""
    return header + "\n\n" + "\n".join(kept) + suffix


def post_tweet(text):
    from requests_oauthlib import OAuth1

    auth = OAuth1(
        os.environ["X_API_KEY"],
        os.environ["X_API_SECRET"],
        os.environ["X_ACCESS_TOKEN"],
        os.environ["X_ACCESS_SECRET"],
    )
    resp = requests.post(
        "https://api.x.com/2/tweets",
        auth=auth,
        json={"text": text},
        timeout=15,
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"X API error {resp.status_code}: {resp.text}")
    return resp.json()


def main():
    now_et = get_us_now()
    month, day = now_et.month, now_et.day
    today_str = now_et.strftime("%Y-%m-%d")
    manual = is_manual_run()

    if not manual:
        if now_et.hour != TARGET_HOUR_ET:
            print(f"Not the target hour yet ({now_et.hour}:00 ET, waiting for {TARGET_HOUR_ET}:00 ET). Skipping.")
            return
        if already_posted_today(today_str):
            print(f"Already posted today ({today_str}). Skipping.")
            return

    players = fetch_active_players()
    todays_players = sorted(
        (p for p in players if p["month"] == month and p["day"] == day),
        key=lambda p: p["name"],
    )

    if not todays_players:
        print(f"No active-roster NBA birthdays today ({MONTH_NAMES[month - 1]} {day} US ET). Skipping post.")
        if not manual:
            mark_posted_today(today_str)
        return

    tweet = build_tweet(todays_players, month, day)
    print("--- Tweet content ---")
    print(tweet)
    print("---------------------")

    if os.environ.get("DRY_RUN") == "1":
        print("DRY_RUN=1 set, not posting.")
        return

    result = post_tweet(tweet)
    print("Posted:", result)
    if not manual:
        mark_posted_today(today_str)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

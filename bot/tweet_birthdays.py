"""
Posts a daily tweet listing active NBA players whose birthday it is today,
using US Eastern Time as the reference date (matching how the NBA schedules
games — see the main site's app.js for the same convention).

GitHub's `schedule:` trigger is best-effort and heavily throttled on
low-traffic repos: we ask for every 15 minutes and actually get roughly four
runs a day at unpredictable hours. So this posts on the first run at or after
6pm ET, rather than requiring an exact hour, and guards against repeats with
last_posted.txt (committed back to the repo by the workflow). Every other
invocation exits immediately without calling any API.

Required environment variables (set as GitHub Actions secrets):
    X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET

Set DRY_RUN=1 to print the tweet instead of posting it (no credentials
needed in that mode) — useful for testing the data/formatting locally.

A manual run (GITHUB_EVENT_NAME=workflow_dispatch, or no GITHUB_EVENT_NAME at
all, i.e. running locally) always bypasses both the target-hour check and the
already-posted-today check, so testing isn't blocked by either gate.
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

# Post around the middle of the US day: late enough to be the evening in the
# UK, early enough that it lands before tip-off, which is the whole point —
# a birthday tweet after the games have been played is useless for props.
#
# It has to be a bounded window, not "from X onwards". GitHub's scheduler is
# best-effort: measured over 60 runs, the first cron of the day lands within
# an hour, but later ones have been up to 6.7 hours late. An open-ended
# "post from 6pm ET onwards" therefore let a badly delayed run post at 10pm
# ET (3am UK). Outside this window we skip the day instead, on the basis
# that no tweet beats a useless one.
POST_WINDOW_START_ET = 12  # noon ET  == 5pm UK
POST_WINDOW_END_ET = 16    # 4:59pm ET == 9:59pm UK, still before tip-off
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


def fetch_team_roster(session, team_id, attempts=3):
    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}/roster"
    for attempt in range(1, attempts + 1):
        resp = session.get(url, timeout=15)
        if resp.status_code == 200:
            return resp.json()
        if attempt < attempts:
            time.sleep(2 * attempt)
    resp.raise_for_status()


def load_bundled_players():
    """Fall back to the snapshot the website ships with.

    ESPN blocks requests from some IPs (its bot detection is stricter on
    datacenter ranges like GitHub's runners), and a missed tweet is worse
    than a slightly stale roster — birthdays never change, only team
    affiliations do.
    """
    path = Path(__file__).parent.parent / "data" / "players.json"
    players = []
    for p in json.loads(path.read_text()):
        teams = p.get("teams") or []
        team = teams[0] if teams else ""
        # Belt and braces: we only tweet rostered players, and an older
        # snapshot may still contain free agents.
        if not team or team == "Free Agent":
            continue
        players.append({
            "name": p["name"],
            "team": team,
            "month": p["month"],
            "day": p["day"],
            "year": p["year"],
        })
    return players


def fetch_active_players():
    # Deliberately no custom User-Agent header. ESPN's bot detection started
    # returning 403 for our old "nba-birthday-bot/1.0" UA (verified: 4/4
    # blocked with it, 4/4 fine without), which broke the whole run.
    session = requests.Session()

    players = []
    try:
        for team_id, team_name in TEAM_IDS.items():
            data = fetch_team_roster(session, team_id)
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
    except Exception as exc:
        print(f"Live ESPN fetch failed ({exc}); using bundled snapshot instead.")
        return load_bundled_players()

    print(f"Fetched {len(players)} rostered players.")

    if not players:
        print("Live ESPN fetch returned no players; using bundled snapshot instead.")
        return load_bundled_players()
    return players


def get_us_now():
    return datetime.now(ZoneInfo("America/New_York"))


def is_manual_run():
    """True only for a human testing this, which bypasses every gate.

    The external Cloudflare cron also triggers us via workflow_dispatch, but
    it must NOT bypass the gates: without the once-per-day guard it would
    double-post whenever GitHub's own schedule happened to fire too. It
    identifies itself with source=cron and is treated exactly like a
    scheduled run.

    Defaults to manual when GITHUB_EVENT_NAME is unset, which covers running
    the script locally.
    """
    event = os.environ.get("GITHUB_EVENT_NAME", "workflow_dispatch")
    if event != "workflow_dispatch":
        return False
    return os.environ.get("TRIGGER_SOURCE", "manual") != "cron"


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


class DuplicateTweet(Exception):
    """X rejected the post because we already tweeted this exact text."""


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
        # Safety net for a cache miss: if the state file is lost, a later run
        # in the same evening window retries the identical text and X rejects
        # it. That means the tweet is already up, so it's a success for our
        # purposes — not something worth failing the build (and emailing) over.
        if resp.status_code == 403 and "duplicate content" in resp.text.lower():
            raise DuplicateTweet(resp.text)
        raise RuntimeError(f"X API error {resp.status_code}: {resp.text}")
    return resp.json()


def main():
    now_et = get_us_now()
    month, day = now_et.month, now_et.day
    today_str = now_et.strftime("%Y-%m-%d")
    manual = is_manual_run()

    if not manual:
        if already_posted_today(today_str):
            print(f"Already posted today ({today_str}). Skipping.")
            return
        if now_et.hour < POST_WINDOW_START_ET:
            print(
                f"Too early ({now_et.hour}:00 ET); posting window is "
                f"{POST_WINDOW_START_ET}:00-{POST_WINDOW_END_ET}:59 ET. Skipping."
            )
            return
        if now_et.hour > POST_WINDOW_END_ET:
            print(
                f"Too late ({now_et.hour}:00 ET); posting window is "
                f"{POST_WINDOW_START_ET}:00-{POST_WINDOW_END_ET}:59 ET. "
                "Skipping rather than tweeting after tip-off."
            )
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

    try:
        result = post_tweet(tweet)
        print("Posted:", result)
    except DuplicateTweet:
        print("X reports this exact tweet already exists - treating as already posted today.")

    if not manual:
        mark_posted_today(today_str)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

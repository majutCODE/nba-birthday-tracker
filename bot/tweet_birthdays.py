"""
Posts a daily tweet listing active NBA players whose birthday it is today,
using US Eastern Time as the reference date (matching how the NBA schedules
games — see the main site's app.js for the same convention).

Required environment variables (set as GitHub Actions secrets):
    X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET

Set DRY_RUN=1 to print the tweet instead of posting it (no credentials
needed in that mode) — useful for testing the data/formatting locally.
"""

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

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


def get_us_today():
    now = datetime.now(ZoneInfo("America/New_York"))
    return now.month, now.day


FOOTER = "Betting angle: birthday-game scoring bumps. #NBA #NBAProps #SportsBetting"


def build_tweet(todays_players, month, day):
    date_str = f"{MONTH_NAMES[month - 1]} {day}"
    header = f"\U0001F3C0\U0001F382 NBA birthdays today ({date_str}, US ET):"
    lines = [f"- {p['name']} ({p['team']})" for p in todays_players]

    body = header + "\n" + "\n".join(lines)

    if len(body) > TWEET_MAX_LEN:
        # Too long for one tweet (many players share a birthday) — truncate
        # the list and note how many more, rather than dropping the header
        # or splitting into a thread. The player list is the actual value,
        # so it takes priority over the footer below.
        kept = []
        for line in lines:
            remaining = len(lines) - len(kept) - 1
            suffix = f"\n+{remaining} more" if remaining > 0 else ""
            candidate = header + "\n" + "\n".join(kept + [line]) + suffix
            if len(candidate) > TWEET_MAX_LEN:
                break
            kept.append(line)
        remaining = len(lines) - len(kept)
        suffix = f"\n+{remaining} more" if remaining > 0 else ""
        return header + "\n" + "\n".join(kept) + suffix

    # Only tack on the keyword/hashtag footer if it fits without pushing us
    # over the limit — it's a bonus for search reach, not core content.
    with_footer = body + "\n\n" + FOOTER
    if len(with_footer) <= TWEET_MAX_LEN:
        return with_footer
    return body


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
    month, day = get_us_today()
    players = fetch_active_players()
    todays_players = sorted(
        (p for p in players if p["month"] == month and p["day"] == day),
        key=lambda p: p["name"],
    )

    if not todays_players:
        print(f"No active-roster NBA birthdays today ({MONTH_NAMES[month - 1]} {day} US ET). Skipping post.")
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


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

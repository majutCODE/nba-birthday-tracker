"""Regenerate data/players.json from the current ESPN rosters.

This snapshot is the offline fallback for both the tweet bot and the
website, so it quietly goes stale as players change teams — by Oct 2026
the Aug 7 file had 54 players on the wrong team and was missing 66
others. The tweet workflow runs this periodically so it maintains itself.

Reuses the bot's roster fetching so there is only one place that knows how
to talk to ESPN.
"""

import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from tweet_birthdays import TEAM_IDS, fetch_team_roster  # noqa: E402

OUT_PATH = Path(__file__).parent.parent / "data" / "players.json"

# A full league is ~600 players. If ESPN serves partial data we would
# rather keep the existing snapshot than overwrite it with a broken one,
# since this file is exactly what we fall back to when ESPN misbehaves.
MIN_EXPECTED_PLAYERS = 300


def build_players():
    session = requests.Session()
    players = []
    for team_id, team_name in TEAM_IDS.items():
        data = fetch_team_roster(session, team_id)
        for athlete in data.get("athletes", []):
            dob = athlete.get("dateOfBirth")
            if not dob:
                continue
            year, month, day = (int(x) for x in dob[:10].split("-"))
            players.append({
                "id": athlete.get("id"),
                "name": athlete.get("fullName") or athlete.get("displayName"),
                "dob": dob[:10],
                "month": month,
                "day": day,
                "year": year,
                "teams": [team_name],
                "position": (athlete.get("position") or {}).get("abbreviation", ""),
                "jersey": athlete.get("jersey", ""),
                "headshot": (athlete.get("headshot") or {}).get("href", ""),
            })
    players.sort(key=lambda p: (p["month"], p["day"], p["name"]))
    return players


def main():
    players = build_players()
    if len(players) < MIN_EXPECTED_PLAYERS:
        raise SystemExit(
            f"Only got {len(players)} players (expected >= {MIN_EXPECTED_PLAYERS}); "
            "keeping the existing snapshot rather than overwriting it."
        )
    OUT_PATH.write_text(json.dumps(players, indent=0))
    print(f"Wrote {len(players)} players to {OUT_PATH}")


if __name__ == "__main__":
    main()

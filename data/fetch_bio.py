"""
Fetch height/weight/birthdate for every player resolved in raw_player_index.json
via nba_api's commonplayerinfo endpoint. Resumable: skips ids already cached so
a crash/rate-limit mid-run doesn't lose progress.

Output: data/cache/raw_bio.json, keyed by player_id (as string).
"""
import sys
import time

from nba_api.stats.endpoints import commonplayerinfo

from data.utils import load_json, save_json

DELAY_SECONDS = 0.7


def _height_to_inches(height: str) -> int | None:
    if not height or "-" not in height:
        return None
    feet, inches = height.split("-")
    return int(feet) * 12 + int(inches)


def fetch_bio_for(player_id: int, max_retries: int = 4) -> dict | None:
    delay = 2
    for attempt in range(max_retries):
        try:
            info = commonplayerinfo.CommonPlayerInfo(player_id=player_id, timeout=15)
            df = info.get_data_frames()[0]
            if df.empty:
                return None
            row = df.iloc[0]
            return {
                "height_in": _height_to_inches(row["HEIGHT"]),
                "weight_lb": int(row["WEIGHT"]) if str(row["WEIGHT"]).strip() else None,
                "birthdate": str(row["BIRTHDATE"])[:10] if row["BIRTHDATE"] else None,
                "position": row["POSITION"],
            }
        except Exception as e:
            print(f"  retry {attempt+1} for {player_id}: {e}", file=sys.stderr)
            time.sleep(delay)
            delay *= 2
    return None


if __name__ == "__main__":
    index = load_json("raw_player_index.json", {})
    bio = load_json("raw_bio.json", {})

    player_ids = sorted({v["player_id"] for v in index.values()})
    todo = [pid for pid in player_ids if str(pid) not in bio]
    print(f"{len(player_ids)} players total, {len(todo)} remaining to fetch", file=sys.stderr)

    for i, pid in enumerate(todo):
        result = fetch_bio_for(pid)
        if result:
            bio[str(pid)] = result
        if (i + 1) % 25 == 0:
            print(f"[{i+1}/{len(todo)}] fetched, saving checkpoint...", file=sys.stderr)
            save_json("raw_bio.json", bio)
        time.sleep(DELAY_SECONDS)

    save_json("raw_bio.json", bio)
    print(f"Wrote {len(bio)} bios -> raw_bio.json")

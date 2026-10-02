"""
One-off calibration tool — NOT wired into the running app.

Pulls real NBA 2K26 Overall + attribute data from ovrbase.com for every
rostered player, compares it against our own stat-derived ratings, and
reports where our formulas over/under-rate players so domain/ratings.py's
constants can be retuned by hand. Safe to delete once calibration is done;
nothing at runtime depends on this.

Usage:
  venv/bin/python3 -m scripts.calibrate_ratings crawl     # step 1: get player slugs per team
  venv/bin/python3 -m scripts.calibrate_ratings fetch      # step 2: fetch each player's 2K attributes
  venv/bin/python3 -m scripts.calibrate_ratings analyze    # step 3: compare against our own ratings
"""
import re
import sys
import time

import requests

from data.utils import cache_path, load_json, save_json

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

TEAM_SLUG_OVERRIDES = {
    "LAC": "los-angeles-clippers",
    "LAL": "los-angeles-lakers",
    "POR": "portland-trailblazers",
}

ATTR_GROUPS = {
    "interior_scoring": ["Close Shot", "Layup", "Standing Dunk", "Driving Dunk", "Post Hook", "Post Fade", "Post Control"],
    "perimeter_scoring": ["Mid-Range", "Three-Point", "Free Throw"],
    "playmaking": ["Pass Accuracy", "Ball Handle", "Pass IQ", "Pass Vision", "Pass Perception"],
    "rebounding": ["Off. Rebound", "Def. Rebound"],
    "interior_defense": ["Interior D"],
    "perimeter_defense": ["Perimeter D"],
    "athleticism": ["Speed", "Strength", "Vertical", "Agility", "Stamina"],
}


def _get(url: str, max_retries: int = 6) -> requests.Response | None:
    delay = 2
    for _ in range(max_retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
        except requests.exceptions.RequestException as e:
            print(f"  connection error on {url}: {e}", file=sys.stderr)
            time.sleep(delay)
            delay = min(delay * 2, 30)
            continue
        if resp.status_code == 200:
            return resp
        if resp.status_code == 404:
            return None
        time.sleep(delay)
        delay = min(delay * 2, 30)
    return None


def crawl_team_slugs():
    from nba_api.stats.static import teams as nba_teams

    result = load_json("ovrbase_player_slugs.json", {})
    for t in nba_teams.get_teams():
        abbr = t["abbreviation"]
        team_slug = TEAM_SLUG_OVERRIDES.get(abbr, t["full_name"].lower().replace(" ", "-"))
        resp = _get(f"https://ovrbase.com/nba/teams/{team_slug}")
        if resp is None:
            print(f"MISS team page: {abbr} ({team_slug})", file=sys.stderr)
            continue
        slugs = sorted(set(re.findall(r"/nba/([a-z0-9\-]+-\d+)", resp.text)))
        result[abbr] = slugs
        print(f"{abbr}: {len(slugs)} player slugs", file=sys.stderr)
        time.sleep(0.4)
    save_json("ovrbase_player_slugs.json", result)
    total = sum(len(v) for v in result.values())
    print(f"Wrote {total} player slugs across {len(result)} teams")


def _parse_player_page(html: str) -> dict | None:
    overall_match = re.search(r'"Overall Rating","value":(\d+)', html)
    if not overall_match:
        return None
    overall = int(overall_match.group(1))

    attrs = {}
    for name, val in re.findall(r'>([A-Za-z][A-Za-z\. \-]+?)</span><span class="inline-flex[^>]*>(\d+)</span>', html):
        attrs[name.strip()] = int(val)

    return {"overall": overall, "attributes": attrs}


def fetch_player_attributes():
    slugs_by_team = load_json("ovrbase_player_slugs.json", {})
    all_slugs = sorted({s for slugs in slugs_by_team.values() for s in slugs})
    cache = load_json("ovrbase_ratings.json", {})
    todo = [s for s in all_slugs if s not in cache]
    print(f"{len(all_slugs)} total, {len(todo)} remaining", file=sys.stderr)

    for i, slug in enumerate(todo):
        try:
            resp = _get(f"https://ovrbase.com/nba/{slug}")
            if resp is not None:
                parsed = _parse_player_page(resp.text)
                if parsed:
                    cache[slug] = parsed
        except Exception as e:
            print(f"  unexpected error on {slug}: {e}", file=sys.stderr)
        if (i + 1) % 10 == 0:
            print(f"[{i+1}/{len(todo)}] saving checkpoint...", file=sys.stderr)
            save_json("ovrbase_ratings.json", cache)
        time.sleep(0.8)

    save_json("ovrbase_ratings.json", cache)
    print(f"Wrote {len(cache)} players -> ovrbase_ratings.json")


def analyze():
    import statistics

    from domain.player import load_players_from_cache
    from domain.ratings import CATEGORIES

    ovr_ratings = load_json("ovrbase_ratings.json", {})
    slugs_by_team = load_json("ovrbase_player_slugs.json", {})

    # ovrbase slug -> person_id (trailing number)
    slug_to_id = {s: int(s.rsplit("-", 1)[1]) for slugs in slugs_by_team.values() for s in slugs}
    id_to_2k = {slug_to_id[s]: v for s, v in ovr_ratings.items() if s in slug_to_id}

    our_players = load_players_from_cache()

    matched = []
    for p in our_players.values():
        if p.player_id in id_to_2k:
            matched.append((p, id_to_2k[p.player_id]))

    print(f"Matched {len(matched)} players between our data and OVRBase\n")

    # --- Overall comparison ---
    diffs = [(ours.overall_rating - theirs["overall"]) for ours, theirs in matched]
    print("=== OVERALL ===")
    print(f"mean diff (ours - 2K): {statistics.mean(diffs):+.1f}")
    print(f"stdev: {statistics.pstdev(diffs):.1f}")
    print(f"our range: {min(p.overall_rating for p,_ in matched)}-{max(p.overall_rating for p,_ in matched)}")
    print(f"2K range:  {min(t['overall'] for _,t in matched)}-{max(t['overall'] for _,t in matched)}")
    worst = sorted(matched, key=lambda pt: abs(pt[0].overall_rating - pt[1]["overall"]), reverse=True)[:15]
    print("\nBiggest misses (ours vs 2K):")
    for ours, theirs in worst:
        print(f"  {ours.name:25s} {ours.positions[0]:16s} ours={ours.overall_rating:3d}  2K={theirs['overall']:3d}  diff={ours.overall_rating-theirs['overall']:+4d}")

    # --- category correlation ---
    print("\n=== CATEGORY CORRELATION (our percentile vs 2K attribute group avg) ===")
    for cat in CATEGORIES:
        attr_names = ATTR_GROUPS[cat]
        xs, ys = [], []
        for ours, theirs in matched:
            vals = [theirs["attributes"][a] for a in attr_names if a in theirs["attributes"]]
            if not vals:
                continue
            xs.append(ours.percentiles[cat])
            ys.append(statistics.mean(vals))
        if len(xs) < 5:
            print(f"  {cat}: insufficient data ({len(xs)} matched)")
            continue
        r = _pearson(xs, ys)
        print(f"  {cat:20s} n={len(xs):3d}  correlation={r:+.2f}  our_pct_mean={statistics.mean(xs):5.1f}  2k_attr_mean={statistics.mean(ys):5.1f}")


def _pearson(xs, ys) -> float:
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx == 0 or vy == 0:
        return 0.0
    return cov / (vx * vy) ** 0.5


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "crawl":
        crawl_team_slugs()
    elif cmd == "fetch":
        fetch_player_attributes()
    elif cmd == "analyze":
        analyze()
    else:
        print(__doc__)

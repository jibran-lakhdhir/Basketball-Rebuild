"""
Per-player season stat-line generation, anchored on each player's own real
2025-26 per-game rates (not synthesized purely from letter grades), plus
season-level noise. Lineup role changes (promoted to starter, buried on the
bench) scale minutes and minutes-correlated counting stats.
"""
import random

from domain.player import Player

TARGET_MPG = {"starter": 32.0, "bench_top": 22.0, "bench_deep": 12.0}
COUNTING_STATS = ["ppg", "rpg", "apg", "spg", "bpg", "topg"]


def role_for(player_id: str, starters: list[str], bench_rotation: list[str]) -> tuple[str, int]:
    if player_id in starters:
        return "starter", 0
    idx = bench_rotation.index(player_id) if player_id in bench_rotation else len(bench_rotation)
    return ("bench_top" if idx < 3 else "bench_deep"), idx


def minutes_multiplier(player: Player, role: str) -> float:
    base_mpg = player.stats.get("mpg") or TARGET_MPG[role]
    target = TARGET_MPG[role]
    multiplier = target / base_mpg if base_mpg else 1.0
    return max(0.4, min(2.0, multiplier))


def simulate_player_season(
    player: Player, role: str, games_in_season: int, rng: random.Random
) -> dict:
    mult = minutes_multiplier(player, role)
    base = player.stats
    base_gp = player.games_played or games_in_season

    gp = round(rng.gauss(base_gp, max(1.0, base_gp * 0.08)))
    gp = max(1, min(games_in_season, gp))

    line = {"gp": gp}
    line["mpg"] = round(max(0.0, (base.get("mpg") or 0) * mult * rng.gauss(1.0, 0.04)), 1)
    for key in COUNTING_STATS:
        val = (base.get(key) or 0) * mult * rng.gauss(1.0, 0.06)
        line[key] = round(max(0.0, val), 1)
    line["fg_pct"] = round(min(0.75, max(0.0, (base.get("fg_pct") or 0) * rng.gauss(1.0, 0.03))), 3)
    line["fg3_pct"] = round(min(0.65, max(0.0, (base.get("fg3_pct") or 0) * rng.gauss(1.0, 0.05))), 3)
    return line


def simulate_single_game_line(player: Player, role: str, rng: random.Random) -> dict:
    """
    One game's stat line. Unlike simulate_player_season, there's no `gp`
    (this IS one game) and much higher relative variance, since single-game
    output genuinely swings a lot night to night (a 25ppg scorer can go for
    10 or 40 on a given night) where a season average smooths that out.
    Noise levels here are eyeballed/ad-hoc, not calibrated against real
    single-game data the way the season-long ratings were.
    """
    mult = minutes_multiplier(player, role)
    base = player.stats

    line = {"mpg": round(max(0.0, (base.get("mpg") or 0) * mult * rng.gauss(1.0, 0.12)), 1)}
    for key in COUNTING_STATS:
        val = (base.get(key) or 0) * mult * rng.gauss(1.0, 0.40)
        line[key] = round(max(0.0, val), 1)
    line["fg_pct"] = round(min(0.85, max(0.0, (base.get("fg_pct") or 0) * rng.gauss(1.0, 0.20))), 3)
    line["fg3_pct"] = round(min(0.75, max(0.0, (base.get("fg3_pct") or 0) * rng.gauss(1.0, 0.30))), 3)
    # Attempts, simulated the same way as the other counting stats -- lets
    # season accumulation derive a properly volume-weighted FG%/3P% (total
    # makes / total attempts) instead of averaging per-game percentages.
    line["fga"] = round(max(0.0, (base.get("fga_pg") or 0) * mult * rng.gauss(1.0, 0.35)), 1)
    line["fg3a"] = round(max(0.0, (base.get("fg3a_pg") or 0) * mult * rng.gauss(1.0, 0.35)), 1)
    return line


def simulate_team_single_game_box_score(
    roster_players: dict[str, Player],
    starters: list[str],
    bench_rotation: list[str],
    rng: random.Random,
) -> dict[str, dict]:
    box_score = {}
    for player_id, player in roster_players.items():
        role, _ = role_for(player_id, starters, bench_rotation)
        if role == "bench_deep" and player_id not in bench_rotation:
            continue  # not in the rotation at all -> no line generated
        box_score[player_id] = simulate_single_game_line(player, role, rng)
    return box_score


def simulate_team_box_score(
    roster_players: dict[str, Player],
    starters: list[str],
    bench_rotation: list[str],
    games_in_season: int,
    rng: random.Random,
) -> dict[str, dict]:
    box_score = {}
    for player_id, player in roster_players.items():
        role, _ = role_for(player_id, starters, bench_rotation)
        if role == "bench_deep" and player_id not in bench_rotation:
            continue  # not in the rotation at all -> no season stats generated
        box_score[player_id] = simulate_player_season(player, role, games_in_season, rng)
    return box_score

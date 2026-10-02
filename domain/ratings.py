"""
Derives the 7 category letter grades (A+ through F) + Overall for every
player from real stats, nudged by height/weight. Percentile-based within
the full player pool (rostered + free agents together) — must run as a
single batch pass since percentiles require the whole population.
"""
import statistics

from domain.positions import primary_position_code

CATEGORIES = [
    "interior_scoring",
    "perimeter_scoring",
    "playmaking",
    "rebounding",
    "interior_defense",
    "perimeter_defense",
    "athleticism",
]

OVERALL_WEIGHTS = {
    "interior_scoring": 0.15,
    "perimeter_scoring": 0.15,
    "playmaking": 0.15,
    "rebounding": 0.12,
    "interior_defense": 0.12,
    "perimeter_defense": 0.13,
    "athleticism": 0.18,
}

# Position-aware Overall weighting: a category a player's position rarely
# asks of them (e.g. Interior Defense for a shooting guard) should still
# count toward Overall, just less. These multipliers scale OVERALL_WEIGHTS
# per position and are renormalized to sum to 1.0, so weak off-position
# categories dent Overall a little rather than a lot, without disappearing.
_HIGH, _MED, _LOW = 1.5, 1.0, 0.5

POSITION_CATEGORY_EMPHASIS = {
    "PG": {
        "interior_scoring": _LOW, "perimeter_scoring": _HIGH, "playmaking": _HIGH,
        "rebounding": _LOW, "interior_defense": _LOW, "perimeter_defense": _MED, "athleticism": _MED,
    },
    "SG": {
        "interior_scoring": _LOW, "perimeter_scoring": _HIGH, "playmaking": _MED,
        "rebounding": _LOW, "interior_defense": _LOW, "perimeter_defense": _HIGH, "athleticism": _MED,
    },
    "SF": {
        "interior_scoring": _MED, "perimeter_scoring": _MED, "playmaking": _MED,
        "rebounding": _MED, "interior_defense": _MED, "perimeter_defense": _MED, "athleticism": _MED,
    },
    "PF": {
        "interior_scoring": _HIGH, "perimeter_scoring": _LOW, "playmaking": _LOW,
        "rebounding": _HIGH, "interior_defense": _HIGH, "perimeter_defense": _LOW, "athleticism": _MED,
    },
    "C": {
        "interior_scoring": _HIGH, "perimeter_scoring": _LOW, "playmaking": _LOW,
        "rebounding": _HIGH, "interior_defense": _HIGH, "perimeter_defense": _LOW, "athleticism": _MED,
    },
}


def _weights_for_position(position_code: str) -> dict[str, float]:
    emphasis = POSITION_CATEGORY_EMPHASIS.get(position_code, {c: 1.0 for c in CATEGORIES})
    raw = {c: OVERALL_WEIGHTS[c] * emphasis[c] for c in CATEGORIES}
    total = sum(raw.values())
    return {c: raw[c] / total for c in CATEGORIES}


_WEIGHTS_BY_POSITION = {pos: _weights_for_position(pos) for pos in POSITION_CATEGORY_EMPHASIS}

# (min percentile threshold, letter) checked high-to-low
GRADE_TABLE = [
    (97, "A+"), (93, "A"), (88, "A-"),
    (83, "B+"), (77, "B"), (70, "B-"),
    (62, "C+"), (50, "C"), (38, "C-"),
    (25, "D+"), (12, "D"), (4, "D-"),
    (0, "F"),
]


def percentile_to_grade(pct: float) -> str:
    for threshold, grade in GRADE_TABLE:
        if pct >= threshold:
            return grade
    return "F"


# NBA2K-style Overall: a 0-99 number, but not a plain linear rescale of
# percentile — a linear map would put the median player at ~50, whereas 2K
# (and real perception of pro talent) keeps even bench-caliber pros in the
# 60s and reserves 90+ for a handful of true stars. A floor + exponent curve
# compresses the middle/bottom of the pool while still stretching out the
# top of the distribution.
# Calibrated against real NBA 2K26 ratings (527 matched players, sourced from
# ovrbase.com): grid-searched floor/gamma minimizing mean absolute error
# against actual 2K Overall ratings. Cut mean error from -8.8 (stdev 5.6) to
# -0.02 (stdev 3.66), MAE 2.8. See scripts/calibrate_ratings.py.
OVERALL_99_FLOOR = 72
OVERALL_99_CEIL = 99
OVERALL_99_GAMMA = 3.3


def percentile_to_overall_99(pct: float) -> int:
    frac = max(0.0, min(1.0, pct / 100.0)) ** OVERALL_99_GAMMA
    value = OVERALL_99_FLOOR + (OVERALL_99_CEIL - OVERALL_99_FLOOR) * frac
    return int(round(max(0, min(99, value))))


def _raw_composite(stats: dict, category: str) -> float:
    """
    Raw per-category composite for the 6 categories driven by box-score stats.
    "athleticism" is NOT handled here — it's computed separately in
    compute_all_grades from usage rate + height/weight (see there for why).
    """
    ppg = stats.get("ppg") or 0.0
    fg_pct = stats.get("fg_pct") or 0.0
    fg3_pct = stats.get("fg3_pct") or 0.0
    apg = stats.get("apg") or 0.0
    ast_pct = stats.get("ast_pct") or 0.0
    rpg = stats.get("rpg") or 0.0
    bpg = stats.get("bpg") or 0.0
    spg = stats.get("spg") or 0.0

    # Shot-selection weighting: PPG × FG% alone doesn't separate paint scoring
    # from 3-point scoring (FG% blends both shot types), so an efficient
    # 3-point shooter inflated "interior scoring" too. Weighting by 3-point
    # attempt rate fixes this — calibrated against real 2K26 attribute data:
    # interior correlation 0.47->0.57, perimeter 0.51->0.61.
    fga = stats.get("fga_pg") or 0.0
    fg3a = stats.get("fg3a_pg") or 0.0
    three_par = (fg3a / fga) if fga else 0.0

    if category == "interior_scoring":
        return ppg * (1 - three_par) * fg_pct
    if category == "perimeter_scoring":
        return ppg * three_par * fg3_pct
    if category == "playmaking":
        return apg * max(ast_pct, 1.0)
    if category == "rebounding":
        return rpg
    if category == "interior_defense":
        return bpg
    if category == "perimeter_defense":
        return spg
    raise ValueError(f"unknown category {category} for _raw_composite")


def _zscore(value, mean, stdev) -> float:
    if value is None or stdev == 0:
        return 0.0
    return (value - mean) / stdev


def _bio_nudge(category: str, height_z: float, weight_z: float) -> float:
    if category in ("interior_scoring", "interior_defense", "rebounding"):
        return height_z * 3 + weight_z * 2
    if category in ("perimeter_scoring", "perimeter_defense"):
        return -height_z * 2 - weight_z * 3
    # playmaking + athleticism: no additional nudge here — athleticism
    # already builds height/weight directly into its composite below,
    # applying the nudge again would double-count them.
    return 0.0


def compute_all_grades(players: list[dict]) -> dict[str, dict]:
    """
    players: list of {"id": str, "stats": dict, "height_in": int|None, "weight_lb": int|None,
                       "positions": list[str]}
    Returns {id: {"grades": {category: letter, ...},  # 7 categories, no "overall" key
                  "overall_rating": int (0-99, NBA2K-style, position-weighted),
                  "percentiles": {category: float}, "overall_percentile": float}}
    """
    heights = [p["height_in"] for p in players if p.get("height_in")]
    weights = [p["weight_lb"] for p in players if p.get("weight_lb")]
    usages = [p["stats"].get("usg_pct") for p in players if p["stats"].get("usg_pct")]
    h_mean = statistics.mean(heights) if heights else 0
    h_std = statistics.pstdev(heights) if heights else 0
    w_mean = statistics.mean(weights) if weights else 0
    w_std = statistics.pstdev(weights) if weights else 0
    u_mean = statistics.mean(usages) if usages else 0
    u_std = statistics.pstdev(usages) if usages else 0

    # Athleticism composite: real per-36 stocks (STL+BLK) turned out to have
    # ~0 correlation with actual NBA 2K26 athletic attributes (Speed/Vertical/
    # Strength/Agility) — pure noise, confirmed via calibration. The best
    # available replacement from stats we have is usage rate (explosive,
    # ball-dominant players skew more athletic) combined with height/weight
    # (shorter/lighter skews more athletic) — correlation 0 -> 0.45.
    def _athleticism_composite(p: dict) -> float:
        uz = _zscore(p["stats"].get("usg_pct"), u_mean, u_std)
        hz = _zscore(p.get("height_in"), h_mean, h_std)
        wz = _zscore(p.get("weight_lb"), w_mean, w_std)
        return 1.2 * uz - 0.7 * hz - 0.5 * wz

    composites = {cat: {} for cat in CATEGORIES}
    for p in players:
        for cat in CATEGORIES:
            if cat == "athleticism":
                composites[cat][p["id"]] = _athleticism_composite(p)
            else:
                composites[cat][p["id"]] = _raw_composite(p["stats"], cat)

    percentiles_by_cat = {cat: {} for cat in CATEGORIES}
    for cat in CATEGORIES:
        values = composites[cat]
        ordered = sorted(values, key=lambda pid: values[pid])
        n = len(ordered)
        for rank, pid in enumerate(ordered):
            percentiles_by_cat[cat][pid] = (rank / (n - 1)) * 100 if n > 1 else 50.0

    results = {}
    for p in players:
        pid = p["id"]
        hz = _zscore(p.get("height_in"), h_mean, h_std)
        wz = _zscore(p.get("weight_lb"), w_mean, w_std)

        pcts = {}
        grades = {}
        for cat in CATEGORIES:
            pct = percentiles_by_cat[cat][pid] + _bio_nudge(cat, hz, wz)
            pct = max(0.0, min(100.0, pct))
            pcts[cat] = pct
            grades[cat] = percentile_to_grade(pct)

        position_code = primary_position_code(p.get("positions", []))
        weights = _WEIGHTS_BY_POSITION.get(position_code, OVERALL_WEIGHTS)
        overall_pct = sum(pcts[c] * weights[c] for c in CATEGORIES)

        results[pid] = {
            "grades": grades,
            "overall_rating": percentile_to_overall_99(overall_pct),
            "percentiles": pcts,
            "overall_percentile": overall_pct,
        }
    return results

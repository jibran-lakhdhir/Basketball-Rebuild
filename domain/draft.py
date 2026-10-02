"""
Original draft prospect generator. Produces fictional players -- no real
names or real scouting data, since we don't have rights to any specific
real 2027 draft class -- but reuses the SAME letter-grade/Overall math real
rostered players go through (domain.ratings), so a drafted prospect looks
and behaves identically to any other player once they're in the league.

get_draft_class() is the one entry point game.py calls. It's a thin wrapper
around generate_draft_class() on purpose: if a real draft class ever becomes
available later, swapping the body of get_draft_class() to read that data
instead is the only change needed -- the lottery and draft-day mechanics in
game.py don't know or care where prospects come from.
"""
import random
from dataclasses import dataclass, field

from domain.dev_tier import DevTier
from domain.ratings import CATEGORIES, _WEIGHTS_BY_POSITION, percentile_to_grade

# NOT domain.ratings.percentile_to_overall_99 -- that curve (floor 72) was
# calibrated against the real rostered-NBA population, where even a bench
# player is elite by global standards. A draft class is a much wider talent
# pool -- most prospects will never be full-time NBA rotation players -- so
# it needs its own, lower-floored curve or the whole class collapses toward
# one number the way a floor-72 curve would.
PROSPECT_OVERALL_FLOOR = 55
PROSPECT_OVERALL_CEIL = 92
PROSPECT_OVERALL_GAMMA = 1.8


def _prospect_percentile_to_overall(pct: float) -> int:
    frac = max(0.0, min(1.0, pct / 100.0)) ** PROSPECT_OVERALL_GAMMA
    value = PROSPECT_OVERALL_FLOOR + (PROSPECT_OVERALL_CEIL - PROSPECT_OVERALL_FLOOR) * frac
    return int(round(max(0, min(99, value))))


# dev_tier here means something different than it does for a rostered real
# player: it's a HIDDEN long-term-ceiling flag, not a reflection of debut
# ability -- the whole point is that a prospect's rookie-year grades (above)
# and their eventual outcome are two separate signals in real drafting.
# Baseline weights target real draft hit-rate folklore, not the debut-
# ability curve: most draftees never become difference-makers (Bronze/
# Silver), a modest chunk carve out a real starting job (Gold), a handful
# per class have genuine star equity (Superstar), and a true "generational"
# ceiling (X-Factor) is rare enough that most classes don't have one at all.
_PROSPECT_TIER_BASE_WEIGHTS: dict[DevTier, float] = {
    DevTier.BRONZE: 35.0,
    DevTier.SILVER: 44.5,
    DevTier.GOLD: 15.0,
    DevTier.SUPERSTAR: 5.0,
    DevTier.X_FACTOR: 0.5,
}


def _prospect_dev_tier(overall_pct: float, rng: random.Random) -> DevTier:
    """Rolls the hidden ceiling tier, lightly nudged by debut ability -- a
    generational talent usually *does* look good immediately, but not
    always, and a great debut is no guarantee of a great career. The nudge
    is deliberately soft (roughly a +-25% swing on the top-tier odds,
    dampened further by leaving Silver as the unscaled middle bucket) so
    real steals (modest debut, big ceiling) and real busts (great debut,
    low ceiling) both stay very possible, same as an actual draft."""
    high_factor = 0.75 + (overall_pct / 100) * 0.5  # 0.75 (worst debut) .. 1.25 (best debut)
    low_factor = 1.25 - (overall_pct / 100) * 0.5  # inverse, for Bronze

    weights = dict(_PROSPECT_TIER_BASE_WEIGHTS)
    for tier in (DevTier.GOLD, DevTier.SUPERSTAR, DevTier.X_FACTOR):
        weights[tier] *= high_factor
    weights[DevTier.BRONZE] *= low_factor

    tiers = list(weights.keys())
    return rng.choices(tiers, weights=[weights[t] for t in tiers], k=1)[0]


RAW_POSITIONS = ["POINT GUARD", "SHOOTING GUARD", "SMALL FORWARD", "POWER FORWARD", "CENTER"]
_POSITION_CODES = ["PG", "SG", "SF", "PF", "C"]

# (min_in, max_in, min_lb, max_lb) archetypal size range per position.
_SIZE_RANGE = {
    "PG": (72, 76, 170, 200),
    "SG": (74, 78, 185, 215),
    "SF": (77, 81, 200, 230),
    "PF": (80, 83, 220, 250),
    "C": (82, 87, 230, 270),
}

_FIRST_NAMES = [
    "Marcus", "Jalen", "Deshawn", "Elijah", "Cole", "Tristan", "Amari", "Xavier", "Isaiah", "Malik",
    "Bryce", "Trey", "Corey", "Jaden", "Devin", "Kaden", "Sekou", "Amadou", "Moussa", "Boubacar",
    "Luka", "Nikola", "Marko", "Dario", "Filip", "Aleksej", "Tomas", "Mateo", "Diego", "Rafael",
    "Enzo", "Hugo", "Leo", "Noa", "Kenji", "Haruto", "Yuki", "Wei", "Jian", "Hao",
    "Connor", "Liam", "Ethan", "Owen", "Mason", "Caleb", "Dominic", "Gabriel", "Julian", "Sebastian",
    "Kofi", "Chidi", "Emeka", "Femi", "Themba", "Sipho", "Kwame", "Obi",
]
_LAST_NAMES = [
    "Prince", "Ramsey", "Okafor", "Nwosu", "Mensah", "Adeyemi", "Diallo", "Traore", "Kone", "Sylla",
    "Kovac", "Radic", "Bogdanovic", "Petrovic", "Vidal", "Marinkovic", "Popovic", "Ilic", "Novak", "Horvat",
    "Torres", "Delgado", "Reyes", "Navarro", "Silva", "Costa", "Moreau", "Girard", "Lefevre", "Bernard",
    "Whitfield", "Sinclair", "Donovan", "Pierce", "Sutton", "Harmon", "Winslow", "Marsh", "Chandler", "Lowry",
    "Nakamura", "Watanabe", "Kobayashi", "Zhang", "Liu", "Chen", "Park", "Kim", "Jansen", "de Vries",
]

_MIN_AGE, _MAX_AGE = 19, 22


@dataclass
class Prospect:
    slug: str
    name: str
    positions: list[str]
    height_in: int
    weight_lb: int
    age: int
    stats: dict
    grades: dict
    overall_rating: int
    percentiles: dict = field(default_factory=dict)
    overall_percentile: float = 0.0
    dev_tier: DevTier = DevTier.SILVER


def _random_name(rng: random.Random, used: set[str]) -> str:
    for _ in range(50):
        name = f"{rng.choice(_FIRST_NAMES)} {rng.choice(_LAST_NAMES)}"
        if name not in used:
            used.add(name)
            return name
    # Pool exhausted (shouldn't happen at 60 names from a ~55x50 pool) --
    # disambiguate rather than loop forever.
    name = f"{rng.choice(_FIRST_NAMES)} {rng.choice(_LAST_NAMES)} {rng.randint(2, 99)}"
    used.add(name)
    return name


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _synthetic_stats(category_pct: dict, overall_pct: float, rng: random.Random) -> dict:
    """A believable-looking per-game rate line derived from the prospect's
    generated grades, so the box-score sim (which anchors off player.stats)
    has something realistic to scale once a rookie is on a roster. Not meant
    to be precise -- just non-zero and roughly proportional to talent."""
    mpg = _clamp(8 + (overall_pct / 100) * 24 + rng.gauss(0, 2), 6.0, 34.0)

    scoring_pct = (category_pct["interior_scoring"] + category_pct["perimeter_scoring"]) / 2
    playmaking_pct = category_pct["playmaking"]
    rebounding_pct = category_pct["rebounding"]
    perimeter_def_pct = category_pct["perimeter_defense"]
    interior_def_pct = category_pct["interior_defense"]

    fga_pg = max(1.0, (mpg / 32.0) * (2.0 + scoring_pct / 100 * 13.0))
    three_share = _clamp(
        0.25 + (category_pct["perimeter_scoring"] - category_pct["interior_scoring"]) / 150, 0.1, 0.75
    )
    fg3a_pg = round(fga_pg * three_share, 1)

    fg_pct = round(_clamp(0.40 + scoring_pct / 100 * 0.13 + rng.gauss(0, 0.02), 0.35, 0.58), 3)
    fg3_pct = round(_clamp(0.28 + category_pct["perimeter_scoring"] / 100 * 0.10 + rng.gauss(0, 0.02), 0.24, 0.42), 3)
    ft_pct = round(_clamp(0.65 + scoring_pct / 100 * 0.15 + rng.gauss(0, 0.03), 0.55, 0.90), 3)

    fta_pg = fga_pg * 0.3
    ppg = round(2 * fga_pg * fg_pct + fg3a_pg * fg3_pct + fta_pg * ft_pct, 1)
    rpg = round((mpg / 32.0) * (1.0 + rebounding_pct / 100 * 7.0), 1)
    apg = round((mpg / 32.0) * (0.5 + playmaking_pct / 100 * 6.0), 1)
    spg = round((mpg / 32.0) * (0.3 + perimeter_def_pct / 100 * 1.5), 1)
    bpg = round((mpg / 32.0) * (0.2 + interior_def_pct / 100 * 1.8), 1)
    topg = round((mpg / 32.0) * (0.8 + (100 - playmaking_pct) / 100 * 2.0), 1)

    return {
        "mpg": round(mpg, 1),
        "ppg": ppg,
        "rpg": rpg,
        "apg": apg,
        "spg": spg,
        "bpg": bpg,
        "topg": topg,
        "fg_pct": fg_pct,
        "fg3_pct": fg3_pct,
        "ft_pct": ft_pct,
        "fg3a_pg": fg3a_pg,
        "fga_pg": round(fga_pg, 1),
        "ts_pct": round(_clamp(fg_pct + fg3_pct * 0.15 + rng.gauss(0, 0.02), 0.42, 0.65), 3),
        "usg_pct": round(_clamp(12 + scoring_pct / 100 * 20, 10, 34), 1),
        "ast_pct": round(_clamp(5 + playmaking_pct / 100 * 30, 3, 42), 1),
        "ws_per_48": round(_clamp(-0.02 + overall_pct / 100 * 0.20, -0.05, 0.25), 3),
    }


def _generate_one(index: int, season_label: str, rng: random.Random, used_names: set[str]) -> Prospect:
    pos_code = _POSITION_CODES[index % len(_POSITION_CODES)] if rng.random() < 0.4 else rng.choice(_POSITION_CODES)
    raw_position = RAW_POSITIONS[_POSITION_CODES.index(pos_code)]

    # Right-skewed true-talent draw: most prospects cluster low-to-mid, with
    # a thin tail of lottery-caliber talents -- not every class has a
    # generational star, and busts/steals are just where the AI GMs' actual
    # picks land relative to this, not baked in here.
    base_pct = rng.betavariate(2.0, 5.0) * 100

    category_pct = {}
    for cat in CATEGORIES:
        category_pct[cat] = _clamp(base_pct + rng.gauss(0, 15), 1.0, 99.5)

    weights = _WEIGHTS_BY_POSITION[pos_code]
    overall_pct = sum(category_pct[c] * weights[c] for c in CATEGORIES)

    grades = {c: percentile_to_grade(category_pct[c]) for c in CATEGORIES}
    overall_rating = _prospect_percentile_to_overall(overall_pct)

    min_h, max_h, min_w, max_w = _SIZE_RANGE[pos_code]
    height_in = rng.randint(min_h, max_h)
    weight_lb = rng.randint(min_w, max_w)
    age = rng.randint(_MIN_AGE, _MAX_AGE)

    slug = f"draft{season_label[:4]}p{index:02d}"
    name = _random_name(rng, used_names)
    dev_tier = _prospect_dev_tier(overall_pct, rng)

    return Prospect(
        slug=slug,
        name=name,
        positions=[raw_position],
        height_in=height_in,
        weight_lb=weight_lb,
        age=age,
        stats=_synthetic_stats(category_pct, overall_pct, rng),
        grades=grades,
        overall_rating=overall_rating,
        percentiles=category_pct,
        overall_percentile=overall_pct,
        dev_tier=dev_tier,
    )


def generate_draft_class(season_label: str, count: int, rng: random.Random) -> list[Prospect]:
    used_names: set[str] = set()
    return [_generate_one(i, season_label, rng, used_names) for i in range(count)]


def get_draft_class(season_label: str, count: int, rng: random.Random) -> list[Prospect]:
    """Swappable entry point -- see module docstring."""
    return generate_draft_class(season_label, count, rng)

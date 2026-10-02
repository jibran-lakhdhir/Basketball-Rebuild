"""
Assigns a hidden development tier (Bronze/Silver/Gold/Superstar/Superstar
X-Factor) per player. Progression effects are out of MVP scope, but the
tier is stored now so multi-season progression can be added later without
a data model change. X-Factor is flavor-only for now.

Deterministically seeded per player (hash of id) so re-running the data
pipeline doesn't reshuffle tiers between builds.
"""
import random
from enum import Enum


class DevTier(str, Enum):
    BRONZE = "Bronze"
    SILVER = "Silver"
    GOLD = "Gold"
    SUPERSTAR = "Superstar"
    X_FACTOR = "Superstar X-Factor"


def _distribution_for(age: int, overall_percentile: float) -> list[tuple[DevTier, float]]:
    if overall_percentile >= 97:
        if age <= 27:
            return [(DevTier.SUPERSTAR, 0.55), (DevTier.X_FACTOR, 0.30), (DevTier.GOLD, 0.15)]
        return [(DevTier.SUPERSTAR, 0.70), (DevTier.GOLD, 0.30)]
    if overall_percentile >= 85:
        if age <= 25:
            return [
                (DevTier.GOLD, 0.40), (DevTier.SILVER, 0.35),
                (DevTier.SUPERSTAR, 0.20), (DevTier.X_FACTOR, 0.05),
            ]
        return [(DevTier.GOLD, 0.55), (DevTier.SILVER, 0.40), (DevTier.SUPERSTAR, 0.05)]
    if overall_percentile >= 60:
        if age <= 23:
            return [(DevTier.SILVER, 0.45), (DevTier.GOLD, 0.35), (DevTier.BRONZE, 0.20)]
        return [(DevTier.SILVER, 0.55), (DevTier.BRONZE, 0.30), (DevTier.GOLD, 0.15)]
    return [(DevTier.BRONZE, 0.70), (DevTier.SILVER, 0.30)]


def assign_dev_tier(player_id: str, age: int, overall_percentile: float) -> DevTier:
    rng = random.Random(hash(player_id))
    dist = _distribution_for(age, overall_percentile)
    roll = rng.random()
    cumulative = 0.0
    for tier, prob in dist:
        cumulative += prob
        if roll <= cumulative:
            return tier
    return dist[-1][0]

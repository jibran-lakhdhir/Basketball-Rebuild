"""
Salary cap / contract model.

Abstracted per design: real 2025-26 cap + tax line, flat free-agent price
tiers, dead-cap waiving, and a "Bird-rights-lite" carve-out that lets a team
always re-sign its own pending free agent regardless of cap room.
"""
from dataclasses import dataclass, field
from typing import Optional

from config import (
    DRAFT_PICKS_PER_ROUND,
    FREE_AGENT_TIER_PRICING,
    LUXURY_TAX_LINE,
    ROOKIE_SCALE_ROUND_1_MAX_SALARY,
    ROOKIE_SCALE_ROUND_1_MIN_SALARY,
    ROOKIE_SCALE_ROUND_1_YEARS,
    ROOKIE_SCALE_ROUND_2_SALARY,
    ROOKIE_SCALE_ROUND_2_YEARS,
    SALARY_CAP,
)

# (min 0-99 Overall rating, tier) checked high-to-low
RATING_TO_TIER = [
    (90, "SUPER_MAX"),
    (82, "MAX"),
    (72, "MID"),
    (0, "MINIMUM"),
]

# Contract length assigned when a player doesn't have a real scraped length
# to use (a fallback tier-priced deal, an AI team's auto-renewal, or a fresh
# free-agent signing) -- cheaper deals tend to be shorter "prove it" contracts.
TIER_TO_CONTRACT_YEARS = {"MINIMUM": 1, "MID": 2, "MAX": 3, "SUPER_MAX": 4}


def free_agent_tier_for_rating(overall_rating: int) -> str:
    """Monotonic mapping from a 0-99 Overall rating to a price tier."""
    for threshold, tier in RATING_TO_TIER:
        if overall_rating >= threshold:
            return tier
    return "MINIMUM"


def price_for_rating(overall_rating: int) -> int:
    return FREE_AGENT_TIER_PRICING[free_agent_tier_for_rating(overall_rating)]


def contract_years_for_rating(overall_rating: int) -> int:
    return TIER_TO_CONTRACT_YEARS[free_agent_tier_for_rating(overall_rating)]


def rookie_contract_for_pick(pick_number: int) -> tuple[int, int]:
    """Returns (annual_salary, contract_years) for a drafted rookie."""
    if pick_number > DRAFT_PICKS_PER_ROUND:
        return ROOKIE_SCALE_ROUND_2_SALARY, ROOKIE_SCALE_ROUND_2_YEARS
    frac = (pick_number - 1) / (DRAFT_PICKS_PER_ROUND - 1)
    salary = round(
        ROOKIE_SCALE_ROUND_1_MAX_SALARY - frac * (ROOKIE_SCALE_ROUND_1_MAX_SALARY - ROOKIE_SCALE_ROUND_1_MIN_SALARY)
    )
    return salary, ROOKIE_SCALE_ROUND_1_YEARS


@dataclass
class Contract:
    player_id: str
    annual_salary: int
    is_dead_cap: bool = False
    original_team_id: Optional[str] = None


@dataclass
class TeamCapSheet:
    team_id: str
    active_contracts: list[Contract] = field(default_factory=list)
    dead_cap_contracts: list[Contract] = field(default_factory=list)

    def total_cap_hit(self) -> int:
        return sum(c.annual_salary for c in self.active_contracts) + sum(
            c.annual_salary for c in self.dead_cap_contracts
        )

    def cap_room(self) -> int:
        return max(0, SALARY_CAP - self.total_cap_hit())

    def is_over_cap(self) -> bool:
        return self.total_cap_hit() > SALARY_CAP

    def is_over_tax_line(self) -> bool:
        return self.total_cap_hit() > LUXURY_TAX_LINE

    def find_active(self, player_id: str) -> Optional[Contract]:
        return next((c for c in self.active_contracts if c.player_id == player_id), None)


def can_sign_free_agent(
    signing_team: TeamCapSheet,
    free_agent: Contract,
    is_own_pending_free_agent: bool = False,
) -> tuple[bool, str]:
    """
    Bird-rights-lite + a tax-band exception system:
      - own pending free agent -> always allowed, any amount.
      - team's current total is under the cap -> full room, any amount that fits.
      - team's current total is between the cap and the tax line -> Mid-tier
        exception (deals up to the MID price).
      - team's current total is over the tax line -> Minimum-tier exception only.
    """
    if is_own_pending_free_agent:
        return True, "bird_rights"

    if signing_team.cap_room() >= free_agent.annual_salary:
        return True, "cap_space"

    current_total = signing_team.total_cap_hit()
    if current_total <= LUXURY_TAX_LINE:
        if free_agent.annual_salary <= FREE_AGENT_TIER_PRICING["MID"]:
            return True, "mid_level_exception"
        return False, "insufficient_cap_room"

    if free_agent.annual_salary <= FREE_AGENT_TIER_PRICING["MINIMUM"]:
        return True, "minimum_exception"
    return False, "insufficient_cap_room"


def waive_player(cap_sheet: TeamCapSheet, player_id: str) -> TeamCapSheet:
    """Moves a contract to dead cap. Salary still counts against the cap this season."""
    contract = cap_sheet.find_active(player_id)
    if contract is None:
        raise ValueError(f"No active contract for player {player_id} on team {cap_sheet.team_id}")
    cap_sheet.active_contracts.remove(contract)
    contract.is_dead_cap = True
    cap_sheet.dead_cap_contracts.append(contract)
    return cap_sheet


def sign_free_agent(
    cap_sheet: TeamCapSheet, free_agent: Contract, is_own_pending_free_agent: bool = False
) -> TeamCapSheet:
    allowed, reason = can_sign_free_agent(cap_sheet, free_agent, is_own_pending_free_agent)
    if not allowed:
        raise ValueError(f"Cannot sign {free_agent.player_id}: {reason}")
    cap_sheet.active_contracts.append(free_agent)
    return cap_sheet

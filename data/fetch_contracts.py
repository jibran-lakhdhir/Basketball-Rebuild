"""
Fetch real player contracts by scraping a Wayback Machine snapshot of
Basketball-Reference's contracts page (see config.CONTRACTS_SNAPSHOT_URL for
why we use an archived snapshot rather than the live page).

The snapshot's y1-y6 columns hold real multi-year salary figures. Per product
decision, we don't model player/team option nuance or year-over-year raises:
contract length is just the count of consecutive populated year columns
starting at y1, and salary is a single flat number (the average of those
years' real dollar amounts).

Output: data/cache/raw_contracts.json, keyed by bbref slug -> salary/length.
"""
import re
import sys

from bs4 import BeautifulSoup

from config import CONTRACTS_SNAPSHOT_URL
from data.utils import get_with_backoff, normalize_name, save_json

YEAR_COLUMNS = ["y1", "y2", "y3", "y4", "y5", "y6"]


def fetch_contracts() -> dict[str, dict]:
    print(f"fetching {CONTRACTS_SNAPSHOT_URL}", file=sys.stderr)
    resp = get_with_backoff(CONTRACTS_SNAPSHOT_URL)
    soup = BeautifulSoup(resp.text, "lxml")
    table = soup.find("table", {"id": "player-contracts"})
    if table is None:
        raise RuntimeError("player-contracts table not found on snapshot page")

    contracts = {}
    for row in table.find("tbody").find_all("tr"):
        player_cell = row.find("td", {"data-stat": "player"})
        if player_cell is None:
            continue
        slug = player_cell.get("data-append-csv")
        name = player_cell.get_text(strip=True)

        year_values = []
        for y in YEAR_COLUMNS:
            cell = row.find("td", {"data-stat": y})
            text = cell.get_text(strip=True) if cell else ""
            amount = int(re.sub(r"[^\d]", "", text)) if text else None
            if amount is None:
                break
            year_values.append(amount)

        if not slug or not year_values:
            continue

        contract_years = len(year_values)
        flat_salary = round(sum(year_values) / contract_years)
        contracts[slug] = {
            "name": name,
            "normalized_name": normalize_name(name),
            "salary_2025_26": year_values[0],
            "flat_salary": flat_salary,
            "contract_years": contract_years,
        }
    return contracts


if __name__ == "__main__":
    data = fetch_contracts()
    save_json("raw_contracts.json", data)
    print(f"Wrote {len(data)} contracts -> raw_contracts.json")

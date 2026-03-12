# Polymarket Scanner

A Python script that scans active Polymarket markets and ranks potential opportunities for **manual decision-making only**.

> This project does **not** execute trades. It only analyzes and ranks markets.

## Files

```text
polymarket_scanner.py
requirements.txt
output/opportunities.csv
README.md
```

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python polymarket_scanner.py
```

The script will:
- Fetch active markets from the Polymarket public API.
- Extract market question, market id, YES/NO price, volume, liquidity, and end date.
- Filter out markets with:
  - volume < 50,000 USD
  - liquidity < 10,000 USD
  - resolved/inactive status
- Compute per-market metrics:
  - `probability_yes = YES price`
  - `probability_no = NO price`
  - `spread = |YES + NO - 1|`
  - `liquidity_score = log(liquidity)`
  - `volume_score = log(volume)`
- Rank by:

```text
opportunity_score =
(2 * spread) +
(0.5 * liquidity_score) +
(0.5 * volume_score)
```

- Print the top 20 opportunities in a formatted table.
- Export results to `output/opportunities.csv`.

## Output CSV

The export contains:
- rank
- market_id
- market_question
- yes_price
- no_price
- volume
- liquidity
- end_date
- spread
- opportunity_score

## Error handling

The script includes explicit error handling for:
- network/API failures
- invalid API responses
- malformed or missing market fields

# Polymarket Scanner

A Python CLI project that scans active Polymarket markets and outputs a ranked list of potential trading opportunities for **manual review only**.

> This tool does not execute trades. It only analyzes markets and surfaces opportunities.

## Project structure

```text
polymarket-scanner/
    polymarket_scanner.py
    config.py
    requirements.txt
    output/
        opportunities.csv
    README.md
```

## Installation

1. (Optional) Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Run the scanner

```bash
python polymarket_scanner.py
```

The script will:
- Fetch all active markets from the Polymarket public Gamma API.
- Filter out likely illiquid/inactive markets:
  - volume < 50,000 USD
  - liquidity < 10,000 USD
  - resolved markets
- Compute ranking metrics.
- Print the top 20 opportunities in a formatted table.
- Export results to `output/opportunities.csv`.

## Opportunity score formula

For each qualifying market:

- `probability_yes = YES price`
- `probability_no = NO price`
- `spread = |YES + NO - 1|`
- `liquidity_score = log(liquidity)`
- `volume_score = log(volume)`

Final score:

```text
opportunity_score =
    (2 * spread) +
    (0.5 * liquidity_score) +
    (0.5 * volume_score)
```

Higher score favors:
- greater pricing inefficiency (`spread`)
- higher liquidity
- higher trading volume

## Notes

- API errors and unexpected payload issues are handled with clear terminal errors.
- Prices are interpreted from common Polymarket market payload shapes (`outcomes + outcomePrices`, token-based, or direct yes/no fields).

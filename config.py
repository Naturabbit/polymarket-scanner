"""Configuration for the Polymarket opportunity scanner."""

API_BASE_URL = "https://gamma-api.polymarket.com/markets"
REQUEST_TIMEOUT_SECONDS = 20
PAGE_SIZE = 500
TOP_N_RESULTS = 20

# Market quality filters
MIN_VOLUME_USD = 50_000
MIN_LIQUIDITY_USD = 10_000

# Output location
OUTPUT_CSV_PATH = "output/opportunities.csv"

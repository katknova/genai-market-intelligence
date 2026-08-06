# src/settings.py

from pathlib import Path
import os

from dotenv import load_dotenv

# -------------------------------------------------------------------
# Paths
# -------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parents[1]   # project root
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
EXTERNAL_DIR = DATA_DIR / "external"

OUTPUTS_DIR = BASE_DIR / "outputs"
FIGURES_DIR = OUTPUTS_DIR / "figures"
TABLES_DIR = OUTPUTS_DIR / "tables"
EXPORTS_DIR = OUTPUTS_DIR / "exports"

DOCS_DIR = BASE_DIR / "docs"
SRC_DIR = BASE_DIR / "src"

# -------------------------------------------------------------------
# Environment variables
# -------------------------------------------------------------------
load_dotenv(BASE_DIR / ".env")

NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")

if not NEWSAPI_KEY:
    raise ValueError(
        "NEWSAPI_KEY not found. Add it to your .env file as NEWSAPI_KEY=your_key_here"
    )

# -------------------------------------------------------------------
# API settings
# -------------------------------------------------------------------
NEWSAPI_BASE_URL = "https://newsapi.org/v2/everything"
NEWSAPI_LANGUAGE = "en"
NEWSAPI_SORT_BY = "publishedAt"
NEWSAPI_PAGE_SIZE = 100  # max allowed by NewsAPI

GOOGLE_NEWS_RSS_BASE_URL = (
    "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
)

REQUEST_TIMEOUT = 30  # seconds

# -------------------------------------------------------------------
# Pipeline settings
# -------------------------------------------------------------------
DEFAULT_DAYS_BACK = 7 # days
MAX_PAGES_PER_QUERY = 1 # pages
MIN_ARTICLE_LENGTH = 50 # words

# -------------------------------------------------------------------
# Project metadata
# -------------------------------------------------------------------
PROJECT_NAME = "The AI Narrative"
PROJECT_VERSION = "0.1.0"

# -------------------------------------------------------------------
# Create folders if they do not exist
# -------------------------------------------------------------------
for folder in [
    RAW_DIR,
    PROCESSED_DIR,
    EXTERNAL_DIR,
    FIGURES_DIR,
    TABLES_DIR,
    EXPORTS_DIR,
]:
    folder.mkdir(parents=True, exist_ok=True)
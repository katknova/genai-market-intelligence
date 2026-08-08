"""
Fetch the full text of news articles collected by the data collectors.

NewsAPI truncates the `content` field to roughly 200 characters, which is
too little for meaningful sentiment analysis. This module visits each
article URL, extracts the main body text, and writes an enriched dataset
to data/processed.
"""

import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests
import trafilatura

from src.settings import (
    RAW_DIR,
    PROCESSED_DIR,
    REQUEST_TIMEOUT,
    MIN_ARTICLE_LENGTH,
    MAX_ARTICLE_LENGTH,
)

# A common desktop browser user-agent used to reduce the chance of
# websites rejecting automated requests. It does not need to exactly
# match your own browser.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Seconds to wait between requests. Scraping politely means not hammering
# a publisher's server with rapid-fire requests.
REQUEST_DELAY = 1.0

# Only use raw CSVs collected within this many days. Older collection runs
# are ignored so the scraper does not keep dragging stale articles along.
RAW_FILE_MAX_AGE_DAYS = 7

# Google News RSS links are redirect stubs, not publisher pages, so they
# cannot be scraped. Any URL on these hosts is skipped.
UNSCRAPEABLE_HOSTS = {"news.google.com"}

# Hosts that can be fetched but are not news coverage. Broad search terms
# such as "GPU" and "Cloud Computing" match package registries and academic
# journals, which are not public discussion of the AI industry and would
# skew the analysis. Skipping them here also avoids pointless requests.
NON_NEWS_HOSTS = {
    # Software package registries and code hosting
    "pypi.org",
    "npmjs.com",
    "github.com",
    # Academic journals and preprint servers
    "nature.com",
    "journals.plos.org",
    "sciencedirect.com",
    "springer.com",
    "arxiv.org",
    "biorxiv.org",
    "mdpi.com",
    "researchgate.net",
    # Aggregators and mailing lists that only carry stubs
    "biztoc.com",
    "lists.w3.org",
    "javascriptweekly.com",
}

# Statuses treated as final. Anything else (a timeout, a blocked request)
# is worth retrying on the next run, so it is not served from the cache.
CACHEABLE_STATUSES = {"ok", "too_short", "too_long"}

# Free-text columns that may contain line breaks from the source data.
# `author` is included because some publishers put multi-line bylines there.
TEXT_COLUMNS = ["title", "author", "description", "content", "analysis_text", "full_text"]

# Matches the _YYYYMMDD_HHMMSS stamp the collectors put in their filenames.
FILENAME_TIMESTAMP = re.compile(r"_(\d{8}_\d{6})\.csv$")


def parse_file_timestamp(path: Path) -> datetime | None:
    """
    Read the collection time out of a raw CSV's filename.

    The collectors name their files like `newsapi_articles_20260806_115526.csv`.
    Using the filename is more reliable than the file's modified date, which
    cloud sync tools such as OneDrive can silently change.
    """
    match = FILENAME_TIMESTAMP.search(path.name)
    if not match:
        return None

    stamp = datetime.strptime(match.group(1), "%Y%m%d_%H%M%S")
    return stamp.replace(tzinfo=timezone.utc)


def load_raw_articles(max_age_days: int | None = RAW_FILE_MAX_AGE_DAYS) -> pd.DataFrame:
    """
    Load and combine raw article CSVs from data/raw.

    Both collectors write the same columns, so the files stack directly on
    top of each other. Pass `max_age_days=None` to load every file
    regardless of age.
    """
    csv_paths = sorted(RAW_DIR.glob("*_articles_*.csv"))

    if max_age_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        kept = []
        for path in csv_paths:
            collected_at = parse_file_timestamp(path)
            if collected_at is None or collected_at >= cutoff:
                kept.append(path)
            else:
                print(f"  Ignoring {path.name} (older than {max_age_days} days)")
        csv_paths = kept

    if not csv_paths:
        raise FileNotFoundError(
            f"No raw article CSVs found in {RAW_DIR} within the last "
            f"{max_age_days} days. Run the collectors in src/data_collection first."
        )

    frames = []
    for path in csv_paths:
        frame = pd.read_csv(path)
        print(f"  Loaded {len(frame):>4} rows from {path.name}")
        frames.append(frame)

    df = pd.concat(frames, ignore_index=True)

    # Later files are the more recent runs, so keep the last copy of any
    # article that appears in more than one collection.
    df = df.drop_duplicates(subset=["dedupe_key"], keep="last").reset_index(drop=True)

    return df


def load_scrape_cache() -> dict[str, dict]:
    """
    Build a lookup of articles already scraped in previous runs.

    Reads the most recent file in data/processed and returns
    {dedupe_key: {"full_text": ..., "scrape_status": ...}} for every
    article whose status is final. Re-scraping those would waste a
    request and hit the publisher for nothing.
    """
    processed_paths = sorted(PROCESSED_DIR.glob("scraped_articles_*.csv"))

    if not processed_paths:
        print("  No previous scrape found - starting fresh")
        return {}

    latest = processed_paths[-1]
    previous = pd.read_csv(latest)

    if "scrape_status" not in previous.columns:
        print(f"  {latest.name} has no scrape_status column - ignoring")
        return {}

    usable = previous[previous["scrape_status"].isin(CACHEABLE_STATUSES)]

    cache = {
        row["dedupe_key"]: {
            "full_text": row["full_text"],
            "scrape_status": row["scrape_status"],
        }
        for _, row in usable.iterrows()
    }

    print(f"  Loaded {len(cache)} cached articles from {latest.name}")
    return cache


def host_matches(netloc: str, hosts: set[str]) -> bool:
    """
    Check a URL's host against a set of domains, including subdomains.

    Publishers are inconsistent about the `www.` prefix and journals use
    subdomains, so `www.nature.com` and `nature.com` must both match the
    single entry "nature.com".
    """
    netloc = netloc.lower().split(":")[0]
    return any(netloc == host or netloc.endswith("." + host) for host in hosts)


def url_skip_reason(url: str | None) -> str | None:
    """
    Decide whether a URL is worth scraping.

    Returns None if the URL should be scraped, otherwise a status string
    explaining why it was skipped. Returning the reason rather than just
    True/False means the output data records *why* an article has no text.
    """
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return "invalid_url"

    netloc = urlparse(url).netloc

    if host_matches(netloc, UNSCRAPEABLE_HOSTS):
        return "unscrapeable"

    if host_matches(netloc, NON_NEWS_HOSTS):
        return "non_news_source"

    return None


def fetch_html(url: str) -> str | None:
    """
    Download the raw HTML of one article.

    Returns None if the request fails for any reason. A single unreachable
    site should never stop the whole run, so all request errors are caught.
    """
    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        print(f"    Request failed: {type(error).__name__}")
        return None

    return response.text


def extract_article_text(html: str, url: str) -> str | None:
    """
    Pull the main body text out of an article's HTML.

    trafilatura strips navigation, adverts, cookie banners and comments,
    leaving just the article body. `url` is passed so it can apply any
    site-specific extraction rules it knows about.
    """
    return trafilatura.extract(
        html,
        url=url,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )


def classify_text(text: str | None) -> str:
    """
    Judge whether extracted text looks like a usable news article.

    This is the single place the length rules live. Both freshly scraped
    text and text reloaded from the cache pass through it, so changing
    MIN/MAX_ARTICLE_LENGTH re-labels the whole dataset on the next run
    instead of only affecting newly fetched articles.
    """
    if not isinstance(text, str) or not text.strip():
        return "extraction_failed"

    # Text is kept either way so a flagged article can still be inspected,
    # but the label lets the analysis exclude it.
    word_count = len(text.split())

    if word_count < MIN_ARTICLE_LENGTH:
        return "too_short"

    if word_count > MAX_ARTICLE_LENGTH:
        return "too_long"

    return "ok"


def scrape_one(url: str) -> tuple[str | None, str]:
    """
    Scrape a single article.

    Returns a (full_text, status) pair. The status explains what happened
    so failures can be counted and investigated rather than silently lost.
    """
    html = fetch_html(url)
    if html is None:
        return None, "request_failed"

    text = extract_article_text(html, url)

    return text, classify_text(text)


def normalize_whitespace(value) -> str | float:
    """
    Collapse all whitespace in a text value down to single spaces.

    Article text arrives with newlines, carriage returns and non-breaking
    spaces embedded in it. Those are valid inside a quoted CSV field, but a
    stray carriage return makes Excel start a new row, which shears the
    table apart on screen. Flattening the text keeps one article on one
    line and loses nothing that matters for sentiment analysis.
    """
    if not isinstance(value, str):
        return value

    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def tidy_text_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply whitespace normalisation to every free-text column present.
    """
    df = df.copy()

    for column in TEXT_COLUMNS:
        if column in df.columns:
            df[column] = df[column].apply(normalize_whitespace)

    return df


def scrape_articles(
    df: pd.DataFrame,
    cache: dict[str, dict] | None = None,
    limit: int | None = None,
) -> pd.DataFrame:
    """
    Scrape the full text for every scrapeable article in `df`.

    Adds four columns: full_text, word_count, scrape_status and scraped_at.
    Articles found in `cache` are reused instead of re-fetched. Set `limit`
    to try a small sample before committing to a full run.
    """
    df = df.copy()
    cache = cache or {}
    df["skip_reason"] = df["url"].apply(url_skip_reason)

    full_texts: dict[int, str | None] = {}
    statuses: dict[int, str] = {}
    pending: list[tuple[int, pd.Series]] = []

    # Split the scrapeable articles into "already known" and "still to do".
    for index, row in df[df["skip_reason"].isna()].iterrows():
        cached = cache.get(row["dedupe_key"])
        if cached is not None:
            # Re-classify rather than reusing the stored status: the text is
            # the fact worth caching, the status is only our reading of it.
            full_texts[index] = cached["full_text"]
            statuses[index] = classify_text(cached["full_text"])
        else:
            pending.append((index, row))

    if limit is not None:
        pending = pending[:limit]

    print(f"\n{len(full_texts)} from cache | {len(pending)} to scrape")
    print("Skipped before fetching:")
    print(df["skip_reason"].value_counts().to_string(), "\n")

    try:
        for counter, (index, row) in enumerate(pending, start=1):
            print(f"[{counter}/{len(pending)}] {row['url'][:80]}")

            text, status = scrape_one(row["url"])
            full_texts[index] = text
            statuses[index] = status

            print(f"    {status}" + (f" ({len(text.split())} words)" if text else ""))

            # Be polite: pause before the next request.
            time.sleep(REQUEST_DELAY)
    except KeyboardInterrupt:
        # Stopping early should still save what we have, so the next run
        # picks these up from the cache instead of re-fetching them.
        print(f"\nInterrupted after {len(statuses)} articles - saving progress")

    # Assigning a Series aligns on the index, so rows that were never
    # visited come back as NaN. Fill those in with the reason why: either
    # the URL was skipped up front, or `limit` stopped us short of it.
    df["full_text"] = pd.Series(full_texts)
    df["scrape_status"] = pd.Series(statuses)
    df["scrape_status"] = (
        df["scrape_status"].fillna(df["skip_reason"]).fillna("not_attempted")
    )
    df["word_count"] = df["full_text"].fillna("").str.split().str.len()
    df["scraped_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    return df.drop(columns=["skip_reason"])


def main() -> None:
    """
    Load raw articles, scrape their full text, and save the result.
    """
    print("Loading raw articles...")
    df = load_raw_articles()
    print(f"  Combined total: {len(df)} unique articles")

    print("\nLoading scrape cache...")
    cache = load_scrape_cache()

    # Set `limit` to a small number to try a sample run; None scrapes
    # everything not already covered by the cache.
    scraped = scrape_articles(df, cache=cache, limit=None)
    scraped = tidy_text_columns(scraped)

    print("\nResults by status:")
    print(scraped["scrape_status"].value_counts().to_string())

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_path = PROCESSED_DIR / f"scraped_articles_{timestamp}.csv"

    scraped.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"\nSaved {len(scraped)} rows to {output_path}")


if __name__ == "__main__":
    main()

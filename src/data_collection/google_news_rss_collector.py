from datetime import datetime, timezone
from urllib.parse import quote_plus

import pandas as pd
import feedparser

from src.entities import SEARCH_TERMS
from src.settings import GOOGLE_NEWS_RSS_BASE_URL, RAW_DIR


def build_rss_url(query: str) -> str:
    """
    Build a Google News RSS search URL for one query term.
    """
    encoded_query = quote_plus(query)
    return GOOGLE_NEWS_RSS_BASE_URL.format(query=encoded_query)


def parse_published_date(entry: dict) -> str | None:
    """
    Convert RSS published time into ISO format if possible.
    """
    published_parsed = entry.get("published_parsed")
    if published_parsed:
        return datetime(*published_parsed[:6], tzinfo=timezone.utc).isoformat(timespec="seconds")

    published = entry.get("published")
    return published


def entry_to_row(entry: dict, query: str) -> dict:
    """
    Convert one RSS entry into a flat table row.
    """
    title = entry.get("title")
    summary = entry.get("summary")
    link = entry.get("link")

    dedupe_key = link or f"{title}|{summary}"

    analysis_text = f"{title or ''}"

    return {
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "query": query,
        "dedupe_key": dedupe_key,
        "source_name": "Google News",
        "author": entry.get("author"),
        "title": title,
        "description": summary,
        "url": link,
        "published_at": parse_published_date(entry),
        "content": summary,
        "analysis_text": analysis_text,
        "source": "Google News RSS"
    }


def collect_google_news_articles() -> pd.DataFrame:
    """
    Fetch RSS entries for all search terms and return a combined DataFrame.
    """
    rows = []

    for query in SEARCH_TERMS:
        print(f"\nQuery: {query}")

        rss_url = build_rss_url(query)
        feed = feedparser.parse(rss_url)

        if hasattr(feed, "bozo") and feed.bozo:
            print(f"Warning: RSS parse issue for query '{query}'")

        entries = feed.entries
        print(f"  Entries: {len(entries)}")

        for entry in entries:
            rows.append(entry_to_row(entry, query))

    df = pd.DataFrame(rows)

    if not df.empty:
        df = df.drop_duplicates(subset=["dedupe_key"]).reset_index(drop=True)

    return df


def main() -> None:
    df = collect_google_news_articles()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_path = RAW_DIR / f"google_news_rss_articles_{timestamp}.csv"

    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"\nSaved {len(df)} rows to {output_path}")


if __name__ == "__main__":
    main()
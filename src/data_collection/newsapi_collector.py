from newsapi import NewsApiClient
from datetime import datetime, timedelta, timezone
import pandas as pd

from src.entities import SEARCH_TERMS
from src.settings import (NEWSAPI_KEY, 
                          DEFAULT_DAYS_BACK, 
                          MAX_PAGES_PER_QUERY,
                          NEWSAPI_LANGUAGE, 
                          NEWSAPI_SORT_BY, 
                          NEWSAPI_PAGE_SIZE, 
                          RAW_DIR
                          )


# Initialise the NewsApiClient with the API key from settings
newsapi = NewsApiClient(api_key=NEWSAPI_KEY)

# Function to build the date range for the NewsAPI query
def build_date_range() -> tuple[str,str]:
    """
    Builds a date range string for the NewsAPI query, based on current date and DEFAULT_DAYS_BACK
    Returns a tuple containing the "from" and "to" dates.
    """
    to_date = datetime.now(timezone.utc).date()
    from_date = to_date - timedelta(days=DEFAULT_DAYS_BACK)

    return (from_date.isoformat(), to_date.isoformat())

def article_to_row(article:dict, query:str) -> dict:
    """
    Converts one NewsAPI article object into a row
    """

    source = article.get("source") or {}
    url = article.get("url")
    title = article.get("title")
    published_at = article.get("publishedAt")

    dedupe_key = url or f"{title}|{published_at}"

    return {
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "query": query,
        "dedupe_key": dedupe_key,
        "source_name": source.get("name"),
        "author": article.get("author"),
        "title": title,
        "description": article.get("description"),
        "url": url,
        "published_at": published_at,
        "content": article.get("content"),
        "analysis_text": f"{title or ''} {article.get('description') or ''}".strip(),
        "source": "newsapi"
    }


def fetch_articles(client:NewsApiClient, query: str, page: int = 1) -> list[dict]:
    """
    Fetches one page of articles for a single search term.
    """
    from_date, to_date = build_date_range()

    response = client.get_everything(
        q=query,
        language=NEWSAPI_LANGUAGE,
        sort_by=NEWSAPI_SORT_BY,
        page_size=NEWSAPI_PAGE_SIZE,
        page=page,
        from_param=from_date,
        to=to_date,
    )

    return response.get("articles", [])

def collect_newsapi_articles() -> pd.DataFrame:
    """
    Pulls articles from NewsAPI for all search terms and returns a DataFrame.
    """
    if not NEWSAPI_KEY:
        raise ValueError(
            "NEWSAPI_KEY not found. Add it to your .env file as NEWSAPI_KEY=your_key_here"
        )

    rows = []

    for query in SEARCH_TERMS:
        print(f"\nQuery: {query}")
        for page in range(1, 2):
            articles = fetch_articles(client=newsapi, query=query, page=page)

            print(f" Page {page}: {len(articles)} articles")

            if not articles:
                break

            for article in articles:
                rows.append(article_to_row(article, query))

            if len(articles) < NEWSAPI_PAGE_SIZE:
                break

    df = pd.DataFrame(rows)

    if not df.empty:
        df = df.drop_duplicates(subset="dedupe_key").reset_index(drop=True)

    return df

def main() -> None:
    """
    Saves a timestamped csv of articles to the raw data folder.
    """

    df = collect_newsapi_articles()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_path = RAW_DIR / f"newsapi_articles_{timestamp}.csv"

    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"\nSaved {len(df)} rows to {output_path}")

if __name__ == "__main__":
    main()
"""
Identify duplicate stories and failed extractions in the scraped dataset.

The same story reaches us more than once: syndicated by several outlets,
published at two URLs by one outlet, or picked up by both collectors. Left
alone, a single story would be counted several times and would quietly
carry extra weight in every sentiment average.

Nothing is deleted here. Rows are flagged instead, so the decisions stay
visible and auditable in the saved file.
"""

import re
from datetime import datetime, timezone

import pandas as pd

from src.settings import PROCESSED_DIR

# Preference order when choosing which row of a duplicate group to keep.
# Lower is better, so a fully scraped article always beats a bare headline.
STATUS_PRIORITY = {
    "ok": 0,
    "too_long": 1,
    "too_short": 2,
    "boilerplate": 3,
    "unscrapeable": 4,
    "non_news_source": 5,
    "request_failed": 6,
    "extraction_failed": 7,
    "not_attempted": 8,
    "invalid_url": 9,
}

# Google News appends " - Publisher Name" to every headline. Removing it
# lets the same story match across our two collectors.
PUBLISHER_SUFFIX = re.compile(r"\s+[-|]\s+[^-|]{2,40}$")


def load_latest_scraped() -> pd.DataFrame:
    """
    Load the most recent scraped_articles CSV from data/processed.
    """
    paths = sorted(PROCESSED_DIR.glob("scraped_articles_*.csv"))

    if not paths:
        raise FileNotFoundError(
            f"No scraped_articles_*.csv found in {PROCESSED_DIR}. "
            "Run src/scraping/article_scraper.py first."
        )

    latest = paths[-1]
    df = pd.read_csv(latest)
    print(f"  Loaded {len(df)} rows from {latest.name}")

    return df


def normalize_title(title) -> str:
    """
    Reduce a headline to a comparable key.

    Strips the publisher suffix, lowercases, and turns punctuation into
    spaces so that "AI data-centre race" and "AI data centre race" match.
    """
    if not isinstance(title, str):
        return ""

    title = PUBLISHER_SUFFIX.sub("", title.strip())
    title = title.lower()
    title = re.sub(r"[^a-z0-9]+", " ", title)

    return title.strip()


def flag_boilerplate(df: pd.DataFrame) -> pd.DataFrame:
    """
    Find rows whose "article text" is really site furniture.

    If several different headlines share character-identical body text,
    that text cannot be any of their articles - the extractor has grabbed
    a navigation menu or headline sidebar instead. Genuine duplicates of
    one story share both the text *and* the headline, so requiring more
    than one distinct title separates the two cases.
    """
    df = df.copy()

    has_text = df["full_text"].notna() & (df["full_text"].astype(str).str.strip() != "")
    candidates = df[has_text]

    grouped = candidates.groupby("full_text")["title"].nunique()
    suspect_texts = set(grouped[grouped > 1].index)

    is_boilerplate = has_text & df["full_text"].isin(suspect_texts)

    print(f"  Flagged {int(is_boilerplate.sum())} rows as boilerplate extractions")

    df.loc[is_boilerplate, "scrape_status"] = "boilerplate"

    return df


def assign_story_ids(df: pd.DataFrame) -> pd.DataFrame:
    """
    Group rows that tell the same story.

    Matching is on the normalised headline. Rows without a usable title
    get their own unique id so they are never merged with anything else.
    """
    df = df.copy()
    df["norm_title"] = df["title"].apply(normalize_title)

    # A blank key would collapse every untitled row into one story, so
    # fall back to the row's own dedupe_key to keep it separate.
    blank = df["norm_title"] == ""
    df.loc[blank, "norm_title"] = "untitled:" + df.loc[blank, "dedupe_key"].astype(str)

    df["story_id"] = df["norm_title"]

    return df.drop(columns=["norm_title"])


def flag_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """
    Within each story, keep the best row and flag the rest.

    "Best" means the most complete version: a successfully scraped article
    beats a headline-only row, longer text beats shorter, and an earlier
    publication date breaks any remaining tie so the original report is
    preferred over later pickups.
    """
    df = df.copy()

    df["status_rank"] = df["scrape_status"].map(STATUS_PRIORITY).fillna(99)
    df["published_sort"] = pd.to_datetime(
        df["published_at"], errors="coerce", utc=True, format="mixed"
    )

    ordered = df.sort_values(
        by=["story_id", "status_rank", "word_count", "published_sort"],
        ascending=[True, True, False, True],
        na_position="last",
    )

    # The first row of each story group is the one we keep.
    df["is_duplicate"] = ordered.duplicated("story_id", keep="first").reindex(df.index)
    df["story_row_count"] = df.groupby("story_id")["story_id"].transform("size")

    return df.drop(columns=["status_rank", "published_sort"])


def deduplicate(df: pd.DataFrame) -> pd.DataFrame:
    """
    Run the full deduplication pass over the scraped dataset.
    """
    df = flag_boilerplate(df)
    df = assign_story_ids(df)
    df = flag_duplicates(df)
    df["deduplicated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    return df


def main() -> None:
    """
    Flag duplicates and boilerplate, then save the annotated dataset.
    """
    print("Loading scraped articles...")
    df = load_latest_scraped()

    print("\nChecking for failed extractions...")
    result = deduplicate(df)

    duplicates = int(result["is_duplicate"].sum())
    print(f"\n  Flagged {duplicates} rows as duplicates of an earlier story")
    print(f"  Distinct stories: {result['story_id'].nunique()}")

    usable = result[(~result["is_duplicate"]) & (result["scrape_status"] == "ok")]
    print(f"\nUsable articles for analysis: {len(usable)}")

    print("\nStatus after deduplication:")
    print(result["scrape_status"].value_counts().to_string())

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_path = PROCESSED_DIR / f"deduplicated_articles_{timestamp}.csv"

    result.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"\nSaved {len(result)} rows to {output_path}")


if __name__ == "__main__":
    main()

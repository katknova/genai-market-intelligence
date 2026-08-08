## NewsAPI
+ Simple API
+ Structures JSON Responses
+ Wide range of news outlets
- Limited to 100 Free requests per day
- Free tier articles delayed by 24 hours
***Selected for analysis***

## Google News RSS
+ Free to access
+ Easy to automate
+ Articles from reputable news outlets
+ Frequent Updates
- Google News RSS gives redirect links whose article IDs are opaque tokens
- No full-text articles from some publishers
- Limited metadata
***Selected for analysis***

## GDELT
+ Free to access
+ Large global news database
+ 15 minute updates
+ Good metadata
+ Google BigQuery access available
- Focused on event metrics, not full-text articles


## Reddit
+ Great source for public opinion
+ Informal source
+ Great for analysing user sentiment
+ Large AI-focused communities available
- Official API access very restrictive
- Greater amount of noise and bias than traditional news

# Full-Text Collection

## Why scraping is necessary
Neither selected source provides usable article text:
- **NewsAPI** truncates `content` to roughly 200 characters, ending in `… [+1464 chars]`.
- **Google News RSS** returns the headline wrapped in HTML link markup as the description.

`src/scraping/article_scraper.py` therefore visits each article URL and extracts
the body text with **trafilatura**, which removes navigation, adverts, cookie
banners and comments. Requests are spaced one second apart.

## Google News RSS links cannot be scraped
Google News RSS does not publish the original article URL. Each `link` is a
redirect stub of the form `news.google.com/rss/articles/CBMi...`, where the
identifier is an opaque token rather than an encoded URL. Following the stub
from an EU IP address is intercepted by Google's consent page, and Google's
internal resolution endpoint rejects unsigned requests.

Working around a consent mechanism was judged out of scope. **Google News RSS is
therefore used for headline-level analysis only**, since its titles are clean and
complete. Its 586 rows are marked `unscrapeable` and excluded from full-text
analysis.

## Exclusion rules
Broad search terms such as `GPU`, `Data Centre` and `Cloud Computing` match
material that is not news coverage. Two filters are applied:

| Rule | Status assigned | Reason |
| --- | --- | --- |
| Blocked domains | `non_news_source` | Package registries (`pypi.org`), academic journals (`nature.com`, `journals.plos.org`), aggregator stubs (`biztoc.com`), mailing lists |
| Over 5,000 words | `too_long` | Research papers, live market blogs and podcast transcripts, not news articles |
| Under 50 words | `too_short` | Paywall teasers |

`pypi.org` alone accounted for 60 rows: Python package descriptions matching the
term "GPU". Academic sources were excluded on methodological grounds as well as
practical ones — a peer-reviewed paper is not *public discussion* of the AI
industry, which is what the research question examines.

Flagged rows keep their text so the decisions remain reversible and auditable.

## Deduplication
`src/preprocessing/deduplicate.py` addresses two problems.

**Failed extractions.** Twenty-one rows shared character-identical body text
across *different* headlines. Identical text under six different headlines cannot
be six articles — the extractor had captured a publisher's headline sidebar
instead of the article. These are marked `boilerplate`. Genuine duplicates share
both text and headline, so requiring more than one distinct title separates the
two cases. Without this check, navigation menus would have entered the analysis
as article content.

**Repeated stories.** The same story arrives syndicated across outlets, published
at two URLs by one outlet, or collected by both collectors. Rows are grouped on a
normalised headline (publisher suffix removed, punctuation flattened) so that
`AI data-centre race` and `AI data centre race` match. Within each group the most
complete row is kept — successfully scraped over headline-only, longer text over
shorter, earlier publication over later. 75 rows were flagged as duplicates.

Rows are flagged rather than deleted, so every decision stays visible in the
saved dataset.

## Collection outcome
From 1,634 unique articles collected:

| Status | Rows | Meaning |
| --- | --- | --- |
| `ok` | 813 | Clean full text extracted |
| `unscrapeable` | 586 | Google News RSS redirect links |
| `non_news_source` | 161 | Blocked domain |
| `request_failed` | 23 | Blocked by publisher, timed out, or dead link |
| `boilerplate` | 21 | Extracted site furniture, not article text |
| `too_long` | 16 | Exceeds the news-article length bound |
| `too_short` | 10 | Paywall teaser |
| `extraction_failed` | 4 | Page could not be parsed |

Of 887 articles actually attempted, 813 yielded clean text — a **91.7% success
rate**. After removing 75 duplicates, **779 articles** are available for
full-text sentiment analysis, alongside 1,559 distinct headlines.

## Known limitations
- **Paywall bias.** Subscription outlets (typically the *Financial Times*, *Wall
  Street Journal*) fail or return teasers, so the sample skews toward freely
  accessible publishers.
- **Headline-only coverage for Google News RSS**, which cannot be mixed directly
  with full-text sentiment scores; article text and headlines carry different
  sentiment characteristics and should be analysed separately.
- **English-language sources only**, per the NewsAPI `language` parameter.
- **Near-duplicate stories are not detected.** Deduplication matches on exact
  normalised headlines, so a rewritten headline over the same wire copy survives
  as a separate story.







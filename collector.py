"""
Module 1: Collector
Searches a subreddit for all mentions of an app name.
Outputs rows for the evidence CSV.
"""

import re
from datetime import datetime, timezone, timedelta
from reddit_client import RedditClient
from config import DEFAULT_SUBREDDIT, RESULTS_PER_PAGE
from sentiment import classify_sentiment


def _parse_date(utc_timestamp: float) -> str:
    """Convert UTC timestamp to readable date string."""
    dt = datetime.fromtimestamp(utc_timestamp, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d")


def _is_within_window(utc_timestamp: float, days: int) -> bool:
    """Check if a timestamp is within the last N days."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
    dt = datetime.fromtimestamp(utc_timestamp, tz=timezone.utc)
    return dt >= cutoff


def _contains_keyword(text: str, keyword: str) -> bool:
    """Case-insensitive keyword check."""
    return keyword.lower() in text.lower()


def _make_comment_url(permalink: str) -> str:
    """Ensure permalink is a full URL."""
    if permalink.startswith("http"):
        return permalink
    return f"https://www.reddit.com{permalink}"


def _extract_thread_title_from_link_title(data: dict) -> str:
    """Try to get thread title from comment data."""
    return data.get("link_title", "") or data.get("title", "") or "[unknown thread]"


def collect_mentions(client: RedditClient, app_name: str,
                     subreddit: str = DEFAULT_SUBREDDIT,
                     days: int = 365,
                     progress_callback=None) -> list[dict]:
    """
    Search a subreddit for all comments and posts mentioning app_name.
    Returns a list of evidence row dicts, deduplicated by comment_url.
    """
    seen_urls = set()
    rows = []

    def _add_row(row: dict):
        url = row["comment_url"]
        if url not in seen_urls:
            seen_urls.add(url)
            rows.append(row)

    # ── Phase 1: Search for comments ──
    if progress_callback:
        progress_callback(f"Searching r/{subreddit} comments for '{app_name}'...")

    after = None
    page = 0
    while True:
        data = client.search_subreddit(subreddit, app_name,
                                        search_type="comment", after=after)
        if not data:
            break

        children = data.get("data", {}).get("children", [])
        if not children:
            break

        for child in children:
            d = child.get("data", {})
            body = d.get("body", "")
            created = d.get("created_utc", 0)
            author = d.get("author", "[deleted]")
            permalink = d.get("permalink", "")

            if not _contains_keyword(body, app_name):
                continue
            if not _is_within_window(created, days):
                continue

            _add_row({
                "username": author,
                "profile_url": f"https://www.reddit.com/user/{author}",
                "subreddit": d.get("subreddit", subreddit),
                "thread_title": _extract_thread_title_from_link_title(d),
                "comment_url": _make_comment_url(permalink),
                "comment_date_text": _parse_date(created),
                "within_last_year": "yes" if _is_within_window(created, 365) else "no",
                "comment_text": body.strip(),
                "source_type": "comment",
                "is_reply": True,
                "sentiment": classify_sentiment(body, app_name),
                "notes": "",
            })

        after = data.get("data", {}).get("after")
        page += 1
        if progress_callback:
            progress_callback(f"  Page {page}: {len(rows)} mentions so far...")
        if not after:
            break

    # ── Phase 2: Search for posts (selftext + title) ──
    if progress_callback:
        progress_callback(f"Searching r/{subreddit} posts for '{app_name}'...")

    after = None
    while True:
        data = client.search_subreddit(subreddit, app_name,
                                        search_type="link", after=after)
        if not data:
            break

        children = data.get("data", {}).get("children", [])
        if not children:
            break

        for child in children:
            d = child.get("data", {})
            title = d.get("title", "")
            selftext = d.get("selftext", "")
            combined = f"{title} {selftext}"
            created = d.get("created_utc", 0)
            author = d.get("author", "[deleted]")
            permalink = d.get("permalink", "")

            if not _is_within_window(created, days):
                continue

            text_for_sentiment = selftext.strip() if selftext.strip() else title

            # App name must appear in the actual stored text, not just the title
            if not _contains_keyword(text_for_sentiment, app_name):
                continue
            _add_row({
                "username": author,
                "profile_url": f"https://www.reddit.com/user/{author}",
                "subreddit": d.get("subreddit", subreddit),
                "thread_title": title,
                "comment_url": _make_comment_url(permalink),
                "comment_date_text": _parse_date(created),
                "within_last_year": "yes" if _is_within_window(created, 365) else "no",
                "comment_text": text_for_sentiment,
                "source_type": "post",
                "is_reply": False,
                "sentiment": classify_sentiment(text_for_sentiment, app_name),
                "notes": "",
            })

        after = data.get("data", {}).get("after")
        if not after:
            break

    if progress_callback:
        progress_callback(f"✓ Collected {len(rows)} mentions from r/{subreddit}")

    return rows


def get_unique_users(rows: list[dict]) -> list[str]:
    """Extract unique usernames from evidence rows, excluding [deleted]."""
    users = set()
    for r in rows:
        u = r["username"]
        if u and u != "[deleted]" and u != "[removed]":
            users.add(u)
    return sorted(users)

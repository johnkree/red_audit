"""
Module 2: Profiler
For each user found in the primary subreddit, scan their public profile
for additional mentions of the app across all of Reddit.
"""

from datetime import datetime, timezone, timedelta
from reddit_client import RedditClient
from config import DEFAULT_SUBREDDIT, IGNORED_SUBREDDITS, is_own_subreddit
from sentiment import classify_sentiment


def _contains_keyword(text: str, keyword: str) -> bool:
    return keyword.lower() in text.lower()


def _parse_date(utc_timestamp: float) -> str:
    dt = datetime.fromtimestamp(utc_timestamp, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d")


def _is_within_window(utc_timestamp: float, days: int) -> bool:
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
    dt = datetime.fromtimestamp(utc_timestamp, tz=timezone.utc)
    return dt >= cutoff


def _make_url(permalink: str) -> str:
    if permalink.startswith("http"):
        return permalink
    return f"https://www.reddit.com{permalink}"


def profile_user(client: RedditClient, username: str, app_name: str,
                 primary_subreddit: str = DEFAULT_SUBREDDIT,
                 days: int = 365,
                 existing_urls: set = None,
                 verbose: bool = False) -> list[dict]:
    """
    Scan a user's public comment and post history for mentions of app_name
    in subreddits OTHER than the primary one.

    Returns evidence rows for cross-subreddit mentions.
    Skips URLs already in existing_urls to avoid duplicates.
    """
    if existing_urls is None:
        existing_urls = set()

    rows = []
    seen = set(existing_urls)

    def _add_row(row: dict):
        url = row["comment_url"]
        if url not in seen:
            seen.add(url)
            rows.append(row)

    # ── Scan comments ──
    after = None
    pages = 0
    while pages < 10:  # safety limit: max 10 pages = 1000 comments
        data = client.get_user_comments(username, after=after)
        if not data:
            if verbose and pages == 0:
                print(f"  ⚠️  Could not access profile for u/{username}")
            break

        children = data.get("data", {}).get("children", [])
        if not children:
            break

        for child in children:
            d = child.get("data", {})
            body = d.get("body", "")
            sub = d.get("subreddit", "")
            created = d.get("created_utc", 0)
            permalink = d.get("permalink", "")

            # Skip primary subreddit (already collected) and ignored subreddits
            if sub.lower() == primary_subreddit.lower():
                continue
            if sub.lower() in IGNORED_SUBREDDITS:
                continue

            if not _is_within_window(created, days):
                continue
            # App name must be in the comment body itself, not just thread metadata
            body_stripped = body.strip()
            if not _contains_keyword(body_stripped, app_name):
                continue

            own_sub = is_own_subreddit(sub, app_name)
            _add_row({
                "username": username,
                "profile_url": f"https://www.reddit.com/user/{username}",
                "subreddit": sub,
                "thread_title": d.get("link_title", "[unknown]"),
                "comment_url": _make_url(permalink),
                "comment_date_text": _parse_date(created),
                "within_last_year": "yes" if _is_within_window(created, 365) else "no",
                "comment_text": body_stripped,
                "source_type": "comment",
                "is_reply": True,
                "sentiment": classify_sentiment(body_stripped, app_name),
                "notes": "Own subreddit" if own_sub else "Cross-subreddit mention",
            })

        after = data.get("data", {}).get("after")
        pages += 1
        if not after:
            break

    # ── Scan posts ──
    after = None
    pages = 0
    while pages < 5:  # posts are fewer, 5 pages = 500 posts
        data = client.get_user_posts(username, after=after)
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
            sub = d.get("subreddit", "")
            created = d.get("created_utc", 0)
            permalink = d.get("permalink", "")

            if sub.lower() == primary_subreddit.lower():
                continue
            if sub.lower() in IGNORED_SUBREDDITS:
                continue

            if not _is_within_window(created, days):
                continue
            text = selftext.strip() if selftext.strip() else title
            # App name must be in the stored text, not just the title
            if not _contains_keyword(text, app_name):
                continue

            own_sub = is_own_subreddit(sub, app_name)
            _add_row({
                "username": username,
                "profile_url": f"https://www.reddit.com/user/{username}",
                "subreddit": sub,
                "thread_title": title,
                "comment_url": _make_url(permalink),
                "comment_date_text": _parse_date(created),
                "within_last_year": "yes" if _is_within_window(created, 365) else "no",
                "comment_text": text,
                "source_type": "post",
                "is_reply": False,
                "sentiment": classify_sentiment(text, app_name),
                "notes": "Own subreddit" if own_sub else "Cross-subreddit mention",
            })

        after = data.get("data", {}).get("after")
        pages += 1
        if not after:
            break

    return rows


def fetch_user_full_history(client: RedditClient, username: str,
                            days: int = 365,
                            progress_callback=None) -> list[dict]:
    """
    Fetch a user's complete comment and post history within the time window.
    No keyword filtering — returns everything for shill pattern analysis.
    """
    rows = []
    seen: set[str] = set()

    def _add_row(row: dict):
        if row["comment_url"] not in seen:
            seen.add(row["comment_url"])
            rows.append(row)

    # ── Comments ──
    after = None
    pages = 0
    while pages < 10:
        data = client.get_user_comments(username, after=after)
        if not data:
            break
        children = data.get("data", {}).get("children", [])
        if not children:
            break
        for child in children:
            d = child.get("data", {})
            created = d.get("created_utc", 0)
            if not _is_within_window(created, days):
                continue
            _add_row({
                "username": username,
                "profile_url": f"https://www.reddit.com/user/{username}",
                "subreddit": d.get("subreddit", ""),
                "thread_title": d.get("link_title", "[unknown]"),
                "comment_url": _make_url(d.get("permalink", "")),
                "comment_date_text": _parse_date(created),
                "within_last_year": "yes" if _is_within_window(created, 365) else "no",
                "comment_text": d.get("body", "").strip(),
                "source_type": "comment",
                "is_reply": True,
                "notes": "",
            })
        after = data.get("data", {}).get("after")
        pages += 1
        if not after:
            break

    # ── Posts ──
    after = None
    pages = 0
    while pages < 5:
        data = client.get_user_posts(username, after=after)
        if not data:
            break
        children = data.get("data", {}).get("children", [])
        if not children:
            break
        for child in children:
            d = child.get("data", {})
            created = d.get("created_utc", 0)
            if not _is_within_window(created, days):
                continue
            title = d.get("title", "")
            selftext = d.get("selftext", "")
            _add_row({
                "username": username,
                "profile_url": f"https://www.reddit.com/user/{username}",
                "subreddit": d.get("subreddit", ""),
                "thread_title": title,
                "comment_url": _make_url(d.get("permalink", "")),
                "comment_date_text": _parse_date(created),
                "within_last_year": "yes" if _is_within_window(created, 365) else "no",
                "comment_text": selftext.strip() if selftext.strip() else title,
                "source_type": "post",
                "is_reply": False,
                "notes": "",
            })
        after = data.get("data", {}).get("after")
        pages += 1
        if not after:
            break

    if progress_callback:
        progress_callback(f"✓ Fetched {len(rows)} posts/comments from u/{username}")

    return rows


def profile_all_users(client: RedditClient, users: list[str], app_name: str,
                      primary_subreddit: str = DEFAULT_SUBREDDIT,
                      days: int = 365,
                      existing_urls: set = None,
                      progress_callback=None,
                      verbose: bool = False) -> list[dict]:
    """
    Profile all users and return combined cross-subreddit evidence rows.
    """
    if existing_urls is None:
        existing_urls = set()

    all_rows = []

    for i, user in enumerate(users, 1):
        if progress_callback:
            progress_callback(f"  Profiling user {i}/{len(users)}: u/{user}...")

        user_rows = profile_user(
            client, user, app_name,
            primary_subreddit=primary_subreddit,
            days=days,
            existing_urls=existing_urls,
            verbose=verbose,
        )
        all_rows.extend(user_rows)

        # Add new URLs to the dedup set
        for r in user_rows:
            existing_urls.add(r["comment_url"])

        if progress_callback and user_rows:
            progress_callback(f"    → Found {len(user_rows)} cross-sub mentions")

    if progress_callback:
        progress_callback(f"✓ Cross-subreddit scan complete: {len(all_rows)} additional mentions")

    return all_rows

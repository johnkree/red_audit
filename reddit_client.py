"""
Reddit HTTP client with rate limiting, backoff, and custom User-Agent.
Uses only Reddit's public .json endpoints — no API key needed.
"""

import time
import json
import requests
from config import (
    USER_AGENT, REQUEST_DELAY, BACKOFF_BASE, BACKOFF_MAX,
    MAX_RETRIES, REQUEST_TIMEOUT
)


class RedditClient:
    """Thin wrapper around requests that handles Reddit rate limiting."""

    def __init__(self, user_agent: str = USER_AGENT, delay: float = REQUEST_DELAY,
                 verbose: bool = False):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self.delay = delay
        self.verbose = verbose
        self._last_request_time = 0.0
        self.request_count = 0
        self.error_count = 0

    def _wait(self):
        """Enforce minimum delay between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)

    def get_json(self, url: str, params: dict = None) -> dict | None:
        """
        Fetch a Reddit .json endpoint with retry + exponential backoff.
        Returns parsed JSON dict or None on failure.
        """
        backoff = BACKOFF_BASE

        for attempt in range(1, MAX_RETRIES + 1):
            self._wait()
            self._last_request_time = time.time()
            self.request_count += 1

            try:
                resp = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)

                if self.verbose:
                    print(f"  [HTTP {resp.status_code}] {url}")

                if resp.status_code == 200:
                    return resp.json()

                if resp.status_code == 429:
                    print(f"  ⏳ Rate limited (429). Waiting {backoff:.0f}s... (attempt {attempt}/{MAX_RETRIES})")
                    time.sleep(backoff)
                    backoff = min(backoff * 2, BACKOFF_MAX)
                    continue

                if resp.status_code in (403, 404):
                    if self.verbose:
                        print(f"  ⚠️  HTTP {resp.status_code} — profile private/suspended/deleted: {url}")
                    return None

                print(f"  ⚠️  HTTP {resp.status_code} for {url} (attempt {attempt})")
                time.sleep(backoff)
                backoff = min(backoff * 2, BACKOFF_MAX)

            except requests.exceptions.Timeout:
                if self.verbose:
                    print(f"  ⏱️  Timeout for {url} (attempt {attempt})")
                else:
                    print(f"  ⏱️  Timeout (attempt {attempt})")
                time.sleep(backoff)
                backoff = min(backoff * 2, BACKOFF_MAX)

            except requests.exceptions.RequestException as e:
                print(f"  ❌ Request error: {e} (attempt {attempt})")
                self.error_count += 1
                time.sleep(backoff)
                backoff = min(backoff * 2, BACKOFF_MAX)

        self.error_count += 1
        return None

    # ── Convenience methods for common Reddit endpoints ──

    def search_subreddit(self, subreddit: str, query: str,
                         search_type: str = "comment", sort: str = "new",
                         after: str = None) -> dict | None:
        """Search a subreddit for posts or comments."""
        url = f"https://www.reddit.com/r/{subreddit}/search.json"
        params = {
            "q": query,
            "sort": sort,
            "restrict_sr": "on",
            "limit": 100,
        }
        if search_type == "comment":
            params["type"] = "comment"
        if after:
            params["after"] = after
        return self.get_json(url, params)

    def get_thread(self, subreddit: str, thread_id: str) -> dict | None:
        """Get a full thread with all comments."""
        url = f"https://www.reddit.com/r/{subreddit}/comments/{thread_id}.json"
        return self.get_json(url, {"limit": 500})

    def get_user_comments(self, username: str, after: str = None) -> dict | None:
        """Get a user's recent comments."""
        url = f"https://www.reddit.com/user/{username}/comments.json"
        params = {"limit": 100, "sort": "new"}
        if after:
            params["after"] = after
        return self.get_json(url, params)

    def get_user_posts(self, username: str, after: str = None) -> dict | None:
        """Get a user's recent posts."""
        url = f"https://www.reddit.com/user/{username}/submitted.json"
        params = {"limit": 100, "sort": "new"}
        if after:
            params["after"] = after
        return self.get_json(url, params)

    def search_reddit(self, query: str, sort: str = "new",
                      after: str = None) -> dict | None:
        """Search all of Reddit (not restricted to a subreddit)."""
        url = "https://www.reddit.com/search.json"
        params = {
            "q": query,
            "sort": sort,
            "limit": 100,
        }
        if after:
            params["after"] = after
        return self.get_json(url, params)

    def stats(self) -> str:
        return f"Requests: {self.request_count} | Errors: {self.error_count}"

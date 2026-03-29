"""
macapps-audit configuration
"""

import re

# === Network ===
USER_AGENT = "macapps-audit/1.0 (mod-tool)"
REQUEST_DELAY = 3.0          # seconds between requests
BACKOFF_BASE = 3.0           # initial backoff on 429
BACKOFF_MAX = 30.0           # max backoff
MAX_RETRIES = 3
REQUEST_TIMEOUT = 15

# === Search ===
DEFAULT_SUBREDDIT = "macapps"
DEFAULT_DAYS = 365
RESULTS_PER_PAGE = 100       # Reddit max

# === Scoring thresholds ===
# Each factor adds to a base score of 0
SCORE_WEIGHTS = {
    # Cross-sub scoring — tiered by intensity
    "cross_sub_2_4": 10,             # 2–4 real cross-sub mentions
    "cross_sub_5_9": 15,             # 5–9 real cross-sub mentions
    "cross_sub_10_19": 20,           # 10–19 real cross-sub mentions
    "cross_sub_20_plus": 30,         # 20+ real cross-sub mentions
    # Other signals
    "high_mention_ratio": 15,        # >50% of user's recent comments mention the app
    "burst_activity": 15,            # ≥3 mentions within 48 hours
    "no_disclosure": 20,             # promotes without ever saying "I built/dev/made"
    "partial_disclosure": 10,        # discloses in some but not all
    "template_wording": 15,          # high similarity across own comments
    "cross_user_similarity": 10,     # high similarity with another user's comments
    "single_purpose_account": 15,    # account seems to exist only for this app
    "giveaway_discount": -10,        # reduce score if mentions are in giveaway threads
    "negative_mention_discount": -5, # per negative mention (max -15 total)
}

# Similarity thresholds
SIMILARITY_THRESHOLD = 0.6   # flag comment pairs above this
TEMPLATE_THRESHOLD = 0.7     # flag self-similar comments above this

# Disclosure phrases (case-insensitive)
DISCLOSURE_PHRASES = [
    "i built", "i made", "i created", "i developed",
    "my app", "our app", "our team", "i'm the dev",
    "i am the dev", "im the dev", "i'm a dev on",
    "i am a dev on", "founder here", "creator here",
    "developer here", "we built", "we made", "we created",
    "i work on", "my project", "our project",
    "as a startup", "i've been making", "i've been building",
]

# Implicit developer phrases — applied only for users with ≥3 mentions (two-pass check)
IMPLICIT_DISCLOSURE_PHRASES = [
    "dev here", "we released", "we just shipped", "just launched",
    "is finally here", "thanks for reporting", "we're working on it",
    "we are working on it", "next version will", "added in v",
    "fixed in v", "coming in v", "update is live",
]

# Giveaway indicators in thread titles (case-insensitive)
GIVEAWAY_PHRASES = [
    "giveaway", "give away", "giving away", "free license",
    "free copies", "promo code", "discount code", "black friday",
    "cyber monday", "launch deal",
]

# Subreddits to ignore entirely during cross-sub profiling
IGNORED_SUBREDDITS = [
    "redditrequest",
]


def is_own_subreddit(subreddit_name: str, app_name: str) -> bool:
    """
    Returns True if the subreddit is likely the official community for the app.
    Checks for the app name (or common slug variations) inside the subreddit name.
    """
    sub_lower = subreddit_name.lower()
    app_slug = re.sub(r'[^a-z0-9]', '', app_name.lower())
    if not app_slug:
        return False

    # Subreddit name contains the app slug (e.g. "droppyformac" ⊃ "droppy")
    if app_slug in sub_lower:
        return True

    # Subreddit IS a known naming pattern for the app
    variations = {
        app_slug,
        app_slug + "app",
        app_slug + "formac",
        app_slug + "official",
        app_slug + "hq",
        "r" + app_slug,
    }
    return sub_lower in variations


# Risk level labels
def risk_label(score: int) -> str:
    if score <= 15:
        return "Low"
    elif score <= 40:
        return "Medium"
    elif score <= 70:
        return "Medium-High"
    else:
        return "High"

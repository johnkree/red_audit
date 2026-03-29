"""
Sentiment classification for Reddit comments mentioning an app.
Keyword-based heuristics only — stdlib, no ML, no API calls.
Accuracy target: ~80%. Edge cases can be improved iteratively.
"""

_NEGATIVE_SIGNALS = [
    "issue", "issues", "bug", "broken", "problem", "terrible", "awful",
    "disappointed", "refund", "scam", "worse", "worst",
    "switched from", "moved away", "don't recommend", "wouldn't recommend",
    "not worth", "overpriced", "vapourware",
    "vaporware", "regret", "stay away", "avoid", "bad experience",
    "poor support", "no support", "crashing", "crashes", "unusable",
    "frustrating", "frustration", "bloated", "abandoned", "dead app",
    "waste of money", "uninstalled", "removed it", "gave up on",
    "stopped using", "keeps crashing", "data loss", "shady", "beware",
]

# Signals that indicate a support/dev response — override negative classification
_SUPPORT_SIGNALS = [
    "you can", "ensure", "let me know", "no worries",
    "thanks for checking", "open a ticket", "please reach out",
    "feel free to", "happy to help", "will be fixed", "working on it",
    "thanks for reporting", "appreciate the", "dev here",
]

_POSITIVE_SIGNALS = [
    "recommend", "love", "great", "best", "amazing", "awesome",
    "try ", "check out", "switched to", "using it", "works great",
    "worth it", "perfect for", "excellent", "fantastic", "brilliant",
    "highly recommend", "must have", "must-have", "game changer",
    "game-changer", "favorite", "favourite", "loving it", "loving this",
    "great app", "love this", "love it", "solid app", "works well",
]

# Phrases indicating the commenter built/owns *something*
_DEVELOPER_PHRASES = [
    "i built", "i made", "my app", "our app", "i'm the dev",
    "i am the dev", "developer here", "we built", "we made",
    "i work on", "my project", "our project", "founder here",
    "creator here", "i created", "i developed", "we created",
    "we developed", "as a developer", "as the developer",
]


def _disclosure_refers_to_app(text_lower: str, app_lower: str) -> bool:
    """
    Returns True if a developer disclosure phrase is immediately followed by
    the target app name (within ~30 chars), indicating they ARE this app's developer.

    A tight window prevents "I built ScreenStudio. FocuSee had tradeoffs." from
    being mistaken as FocuSee's own developer.
    """
    for phrase in _DEVELOPER_PHRASES:
        idx = text_lower.find(phrase)
        if idx == -1:
            continue
        # Tight 15-char window: covers "I built FocuSee" (8 chars after phrase)
        # but excludes "I built ScreenStudio. FocuSee..." (16 chars after phrase)
        window = text_lower[idx + len(phrase): idx + len(phrase) + 15]
        if app_lower in window:
            return True
    return False


def classify_sentiment(text: str, app_name: str) -> str:
    """
    Classify a comment's sentiment toward the named app.

    Returns one of:
      'positive'   — recommends or praises the app
      'negative'   — criticises, complains, or warns about the app
      'neutral'    — mentions without clear valuation (questions, comparisons, etc.)
      'competitor' — commenter promotes a different product; mentions target app
                     only as a comparison or contrast
    """
    if not text or not app_name:
        return "neutral"

    text_lower = text.lower()
    app_lower = app_name.lower()

    # ── Competitor detection ──
    # If the commenter discloses they built *something*, check whether it's
    # this app or a competitor.
    has_dev_disclosure = any(phrase in text_lower for phrase in _DEVELOPER_PHRASES)
    if has_dev_disclosure:
        if not _disclosure_refers_to_app(text_lower, app_lower):
            return "competitor"
        # They ARE this app's developer — fall through to pos/neg/neutral

    # ── Negative vs Positive ──
    neg_count = sum(1 for s in _NEGATIVE_SIGNALS if s in text_lower)
    pos_count = sum(1 for s in _POSITIVE_SIGNALS if s in text_lower)

    # "alternative to" is negative only if the app name follows it
    # e.g. "alternative to FocuSee" = negative; "FocuSee is an alternative to X" = not negative
    if "alternative to" in text_lower:
        idx = text_lower.find("alternative to")
        window = text_lower[idx + len("alternative to"):idx + len("alternative to") + len(app_lower) + 5]
        if app_lower in window:
            neg_count += 1

    if neg_count > pos_count:
        # Support/dev responses: negative keyword present but commenter is helping → neutral
        if any(signal in text_lower for signal in _SUPPORT_SIGNALS):
            return "neutral"
        return "negative"
    if pos_count > 0:
        return "positive"
    return "neutral"

"""
Module 3: Scorer
Computes per-user astroturf probability scores based on evidence rows.
Includes text similarity analysis and disclosure checking.
"""

import re
from difflib import SequenceMatcher
from datetime import datetime, timedelta
from collections import defaultdict, Counter
from config import (
    SCORE_WEIGHTS, SIMILARITY_THRESHOLD, TEMPLATE_THRESHOLD,
    DISCLOSURE_PHRASES, IMPLICIT_DISCLOSURE_PHRASES, GIVEAWAY_PHRASES, risk_label,
)


def _is_giveaway_thread(title: str) -> bool:
    title_lower = title.lower()
    return any(phrase in title_lower for phrase in GIVEAWAY_PHRASES)


def _has_disclosure(text: str, include_implicit: bool = False) -> bool:
    text_lower = text.lower()
    if any(phrase in text_lower for phrase in DISCLOSURE_PHRASES):
        return True
    if include_implicit and any(phrase in text_lower for phrase in IMPLICIT_DISCLOSURE_PHRASES):
        return True
    return False


def _text_similarity(a: str, b: str) -> float:
    """Compute similarity ratio between two texts (0.0 to 1.0)."""
    if not a or not b:
        return 0.0
    # Normalize whitespace
    a = " ".join(a.lower().split())
    b = " ".join(b.lower().split())
    return SequenceMatcher(None, a, b).ratio()


def _detect_bursts(dates: list[str], threshold_hours: int = 48) -> int:
    """Count how many mentions fall within burst windows."""
    if len(dates) < 3:
        return 0

    parsed = sorted(datetime.strptime(d, "%Y-%m-%d") for d in dates)
    burst_count = 0

    for i in range(len(parsed) - 2):
        window = parsed[i + 2] - parsed[i]
        if window <= timedelta(hours=threshold_hours):
            burst_count += 1

    return burst_count


def _propagate_competitor_sentiment(user_rows: dict) -> int:
    """
    Second pass: if >30% of a user's mentions are 'competitor', reclassify
    all their 'neutral' and 'positive' mentions as 'competitor' too.
    Modifies rows in-place. Returns count of reclassified rows.
    """
    reclassified = 0
    for username, rows in user_rows.items():
        if not rows:
            continue
        total = len(rows)
        competitor_count = sum(1 for r in rows if r.get("sentiment") == "competitor")
        if total > 0 and competitor_count / total > 0.30:
            for r in rows:
                if r.get("sentiment") in ("neutral", "positive"):
                    r["sentiment"] = "competitor"
                    old_notes = r.get("notes", "")
                    tag = "Auto-reclassified: user is competitor (>30% competitor mentions)"
                    r["notes"] = f"{old_notes} | {tag}".strip(" | ") if old_notes else tag
                    reclassified += 1
    return reclassified


def _should_skip(row: dict) -> bool:
    """Returns True if a row should be excluded from scoring."""
    notes = row.get("notes", "")
    return (
        "Duplicate" in notes
        or "App name not found" in notes
    )


def compute_user_scores(all_rows: list[dict],
                        primary_subreddit: str = "macapps") -> list[dict]:
    """
    Compute astroturf scores for each user.
    Returns a list of summary dicts for the summary CSV.
    """
    # Group rows by user
    user_rows: dict[str, list[dict]] = defaultdict(list)
    for row in all_rows:
        user_rows[row["username"]].append(row)

    # Competitor propagation pass (modifies rows in-place before scoring)
    _propagate_competitor_sentiment(user_rows)

    # Also collect all "positive" comments (non-critical mentions) for
    # cross-user similarity later
    all_positive_comments = []  # (username, comment_text, url)

    summaries = []

    for username, rows in user_rows.items():
        if username in ("[deleted]", "[removed]"):
            continue

        score = 0
        rationale_parts = []
        similar_evidence = []

        # ── Sentiment & own-sub categorisation ──
        competitor_rows  = [r for r in rows if r.get("sentiment") == "competitor"]
        negative_rows    = [r for r in rows if r.get("sentiment") == "negative"]
        own_sub_rows     = [r for r in rows if r.get("notes") == "Own subreddit"]

        # Rows that count for scoring: exclude competitors and flagged rows
        countable = [r for r in rows
                     if r.get("sentiment") != "competitor"
                     and not _should_skip(r)]

        # Real cross-sub: not primary, not own_sub, not competitor, not skipped
        real_cross = [r for r in countable
                      if r["subreddit"].lower() != primary_subreddit.lower()
                      and r.get("notes", "").split(" | ")[0] != "Own subreddit"]

        primary_rows_c = [r for r in countable
                          if r["subreddit"].lower() == primary_subreddit.lower()]

        own_sub_countable = [r for r in own_sub_rows
                             if r.get("sentiment") != "competitor"
                             and not _should_skip(r)]

        giveaway_rows    = [r for r in countable if _is_giveaway_thread(r["thread_title"])]

        # Rows used for burst/template detection: no own_sub, no competitor, not skipped
        detection_rows = [r for r in countable
                          if r.get("notes", "").split(" | ")[0] != "Own subreddit"]

        n_primary  = len(primary_rows_c)
        n_cross    = len(real_cross)
        n_own_sub  = len(own_sub_countable)
        n_total    = len(countable)
        n_subs     = len(set(r["subreddit"].lower() for r in countable))

        # Reply-weighted cross-sub count: replies count 0.5×
        n_cross_weighted = sum(
            0.5 if r.get("is_reply") else 1.0 for r in real_cross
        )
        n_non_reply_cross = sum(1 for r in real_cross if not r.get("is_reply"))

        # ── Tiered cross-subreddit score (weighted, real cross-sub only) ──
        if n_cross_weighted >= 20:
            score += SCORE_WEIGHTS["cross_sub_20_plus"]
            rationale_parts.append(f"{n_cross} cross-sub mentions across {n_subs} subs")
        elif n_cross_weighted >= 10:
            score += SCORE_WEIGHTS["cross_sub_10_19"]
            rationale_parts.append(f"{n_cross} cross-sub mentions across {n_subs} subs")
        elif n_cross_weighted >= 5:
            score += SCORE_WEIGHTS["cross_sub_5_9"]
            rationale_parts.append(f"{n_cross} cross-sub mentions across {n_subs} subs")
        elif n_cross_weighted >= 2:
            score += SCORE_WEIGHTS["cross_sub_2_4"]
            rationale_parts.append(f"{n_cross} cross-sub mentions")

        # ── Disclosure check: only positive/neutral, non-own-sub mentions ──
        disclosure_base = [r for r in countable
                           if r.get("sentiment") not in ("negative",)
                           and r.get("notes", "").split(" | ")[0] != "Own subreddit"]
        disclosure_texts = [r["comment_text"] for r in disclosure_base]
        n_disc_base      = len(disclosure_texts)

        # Two-pass: include implicit phrases for users with ≥3 total mentions
        use_implicit = n_total >= 3
        disclosures     = [t for t in disclosure_texts if _has_disclosure(t, include_implicit=use_implicit)]
        non_disclosures = [t for t in disclosure_texts if not _has_disclosure(t, include_implicit=use_implicit)]

        # Only apply no/partial disclosure penalty for users with meaningful activity
        has_any_disclosure = bool(disclosures)
        should_check_disclosure = (
            n_total >= 5
            or n_non_reply_cross >= 3
            or has_any_disclosure
        )

        if should_check_disclosure:
            if n_disc_base >= 3 and not disclosures:
                score += SCORE_WEIGHTS["no_disclosure"]
                rationale_parts.append(
                    f"No disclosure in any of {n_disc_base} cross-sub positive/neutral mentions"
                )
            elif disclosures and len(non_disclosures) > len(disclosures):
                score += SCORE_WEIGHTS["partial_disclosure"]
                rationale_parts.append(
                    f"Partial disclosure: {len(disclosures)}/{n_disc_base} cross-sub positive/neutral mentions"
                )

        # ── Negative mention discount (max -15) ──
        n_negative = len(negative_rows)
        if n_negative > 0:
            discount = max(-15, n_negative * SCORE_WEIGHTS["negative_mention_discount"])
            score += discount
            rationale_parts.append(
                f"{n_negative} negative mention(s) reduce score ({discount:+d})"
            )

        # ── Burst detection (detection_rows only, exclude giveaways) ──
        dates = [r["comment_date_text"] for r in detection_rows
                 if not _is_giveaway_thread(r["thread_title"])]
        burst_count = _detect_bursts(dates)
        if burst_count > 0:
            score += SCORE_WEIGHTS["burst_activity"]
            rationale_parts.append(f"Burst activity detected ({burst_count} clusters)")

        # ── Giveaway discount ──
        n_giveaway = len(giveaway_rows)
        if n_giveaway > 0 and n_giveaway == n_total:
            score += SCORE_WEIGHTS["giveaway_discount"]
            rationale_parts.append("All mentions in giveaway/promo threads")
        elif n_total > 0 and n_giveaway > n_total * 0.5:
            score += SCORE_WEIGHTS["giveaway_discount"] // 2
            rationale_parts.append(f"{n_giveaway}/{n_total} mentions in giveaway threads")

        # ── Self-similarity / template detection (detection_rows only) ──
        template_texts = [r["comment_text"] for r in detection_rows]
        if len(template_texts) >= 3:
            high_sim_pairs = []
            for i in range(len(template_texts)):
                for j in range(i + 1, len(template_texts)):
                    sim = _text_similarity(template_texts[i], template_texts[j])
                    if sim >= TEMPLATE_THRESHOLD:
                        high_sim_pairs.append((i, j, sim))

            if high_sim_pairs:
                score += SCORE_WEIGHTS["template_wording"]
                rationale_parts.append(
                    f"Templated wording: {len(high_sim_pairs)} comment pairs with ≥{TEMPLATE_THRESHOLD:.0%} similarity"
                )
                for i, j, sim in high_sim_pairs[:3]:
                    similar_evidence.append(
                        f"[{sim:.0%}] '{template_texts[i][:80]}...' vs '{template_texts[j][:80]}...'"
                    )

        # ── Collect for cross-user comparison (positive/neutral, no own_sub, no giveaway) ──
        for r in rows:
            if (not _is_giveaway_thread(r["thread_title"])
                    and r.get("sentiment") not in ("competitor", "negative")
                    and r.get("notes", "").split(" | ")[0] != "Own subreddit"
                    and not _should_skip(r)):
                all_positive_comments.append((username, r["comment_text"], r["comment_url"]))

        # ── Sentiment breakdown ──
        sentiment_counts = Counter(r.get("sentiment", "neutral") for r in rows)
        sentiment_breakdown = ", ".join(
            f"{v} {k}" for k, v in sentiment_counts.most_common()
        )

        # ── Top subreddits (#5) ──
        sub_counter: Counter = Counter()
        for r in countable:
            sub = r["subreddit"]
            is_own = r.get("notes", "").split(" | ")[0] == "Own subreddit"
            sub_counter[(sub, is_own)] += 1

        top_subs_parts = []
        for (sub, is_own), cnt in sub_counter.most_common(5):
            marker = " (own)" if is_own else ""
            top_subs_parts.append(f"r/{sub}×{cnt}{marker}")
        top_subreddits = ", ".join(top_subs_parts)

        # ── Clamp score ──
        score = max(0, min(95, score))

        summaries.append({
            "username": username,
            "profile_url": f"https://www.reddit.com/user/{username}",
            "macapps_mentions_visible": n_primary,
            "other_sub_mentions_visible": n_cross,
            "own_sub_mentions": n_own_sub,
            "total_visible_mentions": n_total,
            "subreddits_spanned": n_subs,
            "top_subreddits": top_subreddits,
            "astroturf_probability_percent": score,
            "risk_level": risk_label(score),
            "rationale": "; ".join(rationale_parts) if rationale_parts else "Isolated mention, normal activity",
            "sentiment_breakdown": sentiment_breakdown,
            "similar_comment_evidence": " | ".join(similar_evidence) if similar_evidence else "",
        })

    # ── Cross-user similarity pass ──
    _cross_user_similarity(summaries, all_positive_comments)

    # Sort by score descending
    summaries.sort(key=lambda s: s["astroturf_probability_percent"], reverse=True)

    return summaries


def compute_single_user_score(username: str, rows: list[dict]) -> dict:
    """
    Analyze a single user's full activity history for shill patterns.
    Does not require knowing the app upfront — detects the dominant topic automatically.
    Returns a summary dict.
    """
    import re
    from collections import Counter

    if not rows:
        return {
            "username": username,
            "profile_url": f"https://www.reddit.com/user/{username}",
            "total_posts_scanned": 0,
            "unique_subreddits": 0,
            "top_mentioned_product": "",
            "product_concentration_percent": 0,
            "astroturf_probability_percent": 0,
            "risk_level": "Low",
            "rationale": "No activity found in time window",
            "similar_comment_evidence": "",
        }

    score = 0
    rationale_parts = []
    similar_evidence = []

    texts = [r["comment_text"] for r in rows]
    n_total = len(rows)
    unique_subs = len(set(r["subreddit"].lower() for r in rows))

    # ── Detect dominant product/app name ──
    # Find capitalized words (≥4 chars) appearing in multiple posts
    _STOPWORDS = {
        'This', 'That', 'With', 'From', 'Have', 'Been', 'Just', 'When',
        'What', 'Your', 'Some', 'Like', 'Also', 'More', 'Just', 'Even',
        'Only', 'Most', 'Many', 'They', 'Them', 'Their', 'Then', 'Than',
        'Reddit', 'Thanks', 'Thank', 'Please', 'Sorry', 'Really', 'Actually',
        'Great', 'Good', 'Best', 'Love', 'Nice', 'Well', 'Very', 'Much',
        'Here', 'There', 'Into', 'Will', 'Would', 'Could', 'Should',
    }
    cap_pattern = re.compile(r'\b[A-Z][a-zA-Z]{3,}\b')
    word_counter: Counter = Counter()
    for text in texts:
        found = set()
        for m in cap_pattern.finditer(text):
            word = m.group(0)
            if word not in _STOPWORDS:
                found.add(word)
        word_counter.update(found)

    top_product = ""
    product_concentration = 0
    if word_counter:
        candidates = [(w, c) for w, c in word_counter.most_common(20) if c >= 3]
        if candidates:
            top_product, _ = candidates[0]
            posts_with_product = sum(
                1 for t in texts if top_product.lower() in t.lower()
            )
            product_concentration = int(posts_with_product / n_total * 100)

            if product_concentration >= 60:
                score += 25
                rationale_parts.append(
                    f"'{top_product}' in {product_concentration}% of all activity ({posts_with_product}/{n_total} posts)"
                )
            elif product_concentration >= 35:
                score += 12
                rationale_parts.append(
                    f"'{top_product}' in {product_concentration}% of activity"
                )

    # ── Disclosure check ──
    promoting_phrases = [
        'recommend', 'try ', 'check out', 'worth it', 'great app',
        'best app', 'love this', 'highly recommend', 'must have',
    ]
    promotional_texts = [t for t in texts if any(p in t.lower() for p in promoting_phrases)]
    disclosure_texts = [t for t in texts if _has_disclosure(t)]

    if len(promotional_texts) >= 3 and not disclosure_texts:
        score += SCORE_WEIGHTS["no_disclosure"]
        rationale_parts.append(
            f"Promotes products in {len(promotional_texts)} posts without any affiliation disclosure"
        )

    # ── Template detection ──
    sample = texts[:50]
    if len(sample) >= 3:
        high_sim_pairs = []
        for i in range(len(sample)):
            for j in range(i + 1, len(sample)):
                if len(sample[i]) < 50 or len(sample[j]) < 50:
                    continue
                sim = _text_similarity(sample[i], sample[j])
                if sim >= TEMPLATE_THRESHOLD:
                    high_sim_pairs.append((i, j, sim))
        if high_sim_pairs:
            score += SCORE_WEIGHTS["template_wording"]
            rationale_parts.append(
                f"Templated wording: {len(high_sim_pairs)} similar comment pairs"
            )
            for i, j, sim in high_sim_pairs[:3]:
                similar_evidence.append(
                    f"[{sim:.0%}] '{sample[i][:80]}...' vs '{sample[j][:80]}...'"
                )

    # ── Burst activity ──
    dates = [r["comment_date_text"] for r in rows]
    burst_count = _detect_bursts(dates)
    if burst_count > 0:
        score += SCORE_WEIGHTS["burst_activity"]
        rationale_parts.append(f"Burst activity detected ({burst_count} clusters)")

    # ── Cross-subreddit promotion of top product ──
    if top_product:
        product_subs = set(
            r["subreddit"].lower() for r in rows
            if top_product.lower() in r["comment_text"].lower()
        )
        n_prod_subs = len(product_subs)
        if n_prod_subs >= 20:
            score += SCORE_WEIGHTS["cross_sub_20_plus"]
            rationale_parts.append(f"Promotes '{top_product}' across {n_prod_subs} subreddits")
        elif n_prod_subs >= 10:
            score += SCORE_WEIGHTS["cross_sub_10_19"]
            rationale_parts.append(f"Promotes '{top_product}' across {n_prod_subs} subreddits")
        elif n_prod_subs >= 5:
            score += SCORE_WEIGHTS["cross_sub_5_9"]
            rationale_parts.append(f"Promotes '{top_product}' across {n_prod_subs} subreddits")
        elif n_prod_subs >= 2:
            score += SCORE_WEIGHTS["cross_sub_2_4"]
            rationale_parts.append(f"Promotes '{top_product}' in {n_prod_subs} subreddits")

    score = max(0, min(95, score))

    return {
        "username": username,
        "profile_url": f"https://www.reddit.com/user/{username}",
        "total_posts_scanned": n_total,
        "unique_subreddits": unique_subs,
        "top_mentioned_product": top_product,
        "product_concentration_percent": product_concentration,
        "astroturf_probability_percent": score,
        "risk_level": risk_label(score),
        "rationale": "; ".join(rationale_parts) if rationale_parts else "No suspicious patterns detected",
        "similar_comment_evidence": " | ".join(similar_evidence) if similar_evidence else "",
    }


def _cross_user_similarity(summaries: list[dict],
                           comments: list[tuple[str, str, str]]):
    """
    Check for suspiciously similar wording between different users.
    Modifies summaries in-place.
    """
    if len(comments) < 2:
        return

    # Only compare between different users
    user_lookup = {s["username"]: s for s in summaries}

    checked = set()
    for i in range(len(comments)):
        for j in range(i + 1, len(comments)):
            user_a, text_a, url_a = comments[i]
            user_b, text_b, url_b = comments[j]

            if user_a == user_b:
                continue

            pair_key = tuple(sorted([url_a, url_b]))
            if pair_key in checked:
                continue
            checked.add(pair_key)

            sim = _text_similarity(text_a, text_b)
            if sim >= SIMILARITY_THRESHOLD:
                evidence = f"[{sim:.0%} similar to u/{user_b}] '{text_a[:60]}...'"
                evidence_b = f"[{sim:.0%} similar to u/{user_a}] '{text_b[:60]}...'"

                if user_a in user_lookup:
                    s = user_lookup[user_a]
                    s["astroturf_probability_percent"] = min(95,
                        s["astroturf_probability_percent"] + SCORE_WEIGHTS["cross_user_similarity"])
                    existing = s["similar_comment_evidence"]
                    s["similar_comment_evidence"] = f"{existing} | {evidence}".strip(" | ")
                    s["risk_level"] = risk_label(s["astroturf_probability_percent"])

                if user_b in user_lookup:
                    s = user_lookup[user_b]
                    s["astroturf_probability_percent"] = min(95,
                        s["astroturf_probability_percent"] + SCORE_WEIGHTS["cross_user_similarity"])
                    existing = s["similar_comment_evidence"]
                    s["similar_comment_evidence"] = f"{existing} | {evidence_b}".strip(" | ")
                    s["risk_level"] = risk_label(s["astroturf_probability_percent"])

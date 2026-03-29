#!/usr/bin/env python3
"""
macapps-audit — Astroturfing detection tool for Reddit moderators.

Usage:
    python macapps_audit.py "AppName"
    python macapps_audit.py "AppName" --days 180 --subreddit macapps
    python macapps_audit.py "AppName" --skip-profiles   # fast mode, no cross-sub scan
"""

import argparse
import csv
import os
import sys
import time
from collections import defaultdict
from difflib import SequenceMatcher
from datetime import datetime, timezone

from reddit_client import RedditClient
from collector import collect_mentions, get_unique_users
from profiler import profile_all_users, fetch_user_full_history
from scorer import compute_user_scores, compute_single_user_score
from reporter import generate_html_report, generate_llm_prompt, generate_user_html_report
from config import DEFAULT_SUBREDDIT, DEFAULT_DAYS


def _print(msg: str):
    """Timestamped console output."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def write_evidence_csv(rows: list[dict], filepath: str):
    """Write the evidence CSV with proper quoting."""
    fieldnames = [
        "username", "profile_url", "subreddit", "thread_title",
        "comment_url", "comment_date_text", "within_last_year",
        "comment_text", "source_type", "is_reply", "sentiment", "notes",
    ]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL,
                                extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_summary_csv(summaries: list[dict], filepath: str):
    """Write the summary CSV."""
    fieldnames = [
        "username", "profile_url", "macapps_mentions_visible",
        "other_sub_mentions_visible", "own_sub_mentions", "total_visible_mentions",
        "subreddits_spanned", "top_subreddits", "astroturf_probability_percent",
        "risk_level", "rationale", "sentiment_breakdown", "similar_comment_evidence",
    ]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL,
                                extrasaction="ignore")
        writer.writeheader()
        for row in summaries:
            writer.writerow(row)


def _mark_duplicates(evidence: list[dict]) -> int:
    """
    Mark near-duplicate comments (>95% similar text) within each user's rows.
    Later rows get notes updated; they remain in CSV but are excluded from scoring.
    Returns count of marked duplicates.
    """
    user_rows: dict = defaultdict(list)
    for r in evidence:
        user_rows[r["username"]].append(r)

    marked = 0
    for _username, rows in user_rows.items():
        rows_sorted = sorted(rows, key=lambda r: r.get("comment_date_text", ""))
        seen: list[str] = []

        for row in rows_sorted:
            text = row.get("comment_text", "").strip()
            if len(text) < 20:
                seen.append(text)
                continue

            is_dup = False
            norm = " ".join(text.lower().split())
            for prev in seen[-20:]:
                if len(prev) < 20:
                    continue
                prev_norm = " ".join(prev.lower().split())
                if SequenceMatcher(None, norm, prev_norm).ratio() > 0.95:
                    is_dup = True
                    break

            if is_dup:
                old = row.get("notes", "")
                tag = "Duplicate (>95% similar to earlier mention)"
                row["notes"] = f"{old} | {tag}".strip(" | ") if old else tag
                marked += 1

            seen.append(text)

    return marked


def _validate_content(evidence: list[dict], app_name: str) -> int:
    """
    Flag rows where the app name does not appear in comment_text.
    Returns count of flagged rows.
    """
    flagged = 0
    app_lower = app_name.lower()
    for row in evidence:
        if app_lower not in row.get("comment_text", "").lower():
            old = row.get("notes", "")
            tag = "⚠️ App name not found in comment text"
            row["notes"] = f"{old} | {tag}".strip(" | ") if old else tag
            flagged += 1
    return flagged


def _run_user_scan(args):
    """Scan a single Reddit user for shill patterns."""
    username = args.user.lstrip("u/")
    days = args.days
    output_dir = args.output

    print()
    print("╔══════════════════════════════════════════════╗")
    print("║         macapps-audit · v1.0                 ║")
    print("║        User Shill Analysis Mode              ║")
    print("╚══════════════════════════════════════════════╝")
    print()
    _print(f"Target user: u/{username}")
    _print(f"Window: last {days} days")
    _print(f"Output: {output_dir}/")
    print()

    client = RedditClient()
    start_time = time.time()

    # ── Step 1: Fetch full history ──
    _print("STEP 1/3 — Fetching activity history...")
    rows = fetch_user_full_history(client, username, days=days,
                                   progress_callback=_print)
    print()

    if not rows:
        _print("⚠️  No public activity found. Account may be private, suspended, or inactive.")
        sys.exit(0)

    # ── Step 2: Score ──
    _print("STEP 2/3 — Analysing shill patterns...")
    summary = compute_single_user_score(username, rows)
    _print(f"Risk level: {summary['risk_level']} ({summary['astroturf_probability_percent']}%)")
    if summary["top_mentioned_product"]:
        _print(f"Top detected product: {summary['top_mentioned_product']} "
               f"({summary['product_concentration_percent']}% of activity)")
    print()

    # ── Step 3: Output ──
    _print("STEP 3/3 — Writing output files...")

    safe_name = username.replace("/", "_")
    evidence_path = os.path.join(output_dir, f"{safe_name}-Evidence.csv")
    report_path = os.path.join(output_dir, f"{safe_name}-UserReport.html")

    write_evidence_csv(rows, evidence_path)
    _print(f"  📄 {evidence_path} ({len(rows)} rows)")

    html_report = generate_user_html_report(
        username, rows, summary, days=days, client_stats=client.stats()
    )
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html_report)
    _print(f"  🌐 {report_path}")

    elapsed = time.time() - start_time
    print()
    _print(f"✅ Done in {elapsed:.0f}s · {client.stats()}")
    _print(f"Open {report_path} in your browser to review the report.")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Scan Reddit for astroturfing patterns around an app.",
        epilog="Example: python macapps_audit.py FocuSee --days 365",
    )
    parser.add_argument("app_name", nargs="?", default=None,
                        help="App name or keyword to search for")
    parser.add_argument("--user", "-u", default=None,
                        help="Scan a specific Reddit user for shill patterns (skips app search)")
    parser.add_argument("--subreddit", "-s", default=DEFAULT_SUBREDDIT,
                        help=f"Primary subreddit to scan (default: {DEFAULT_SUBREDDIT})")
    parser.add_argument("--days", "-d", type=int, default=DEFAULT_DAYS,
                        help=f"Time window in days (default: {DEFAULT_DAYS})")
    parser.add_argument("--output", "-o", default="output",
                        help="Output directory (default: output/)")
    parser.add_argument("--skip-profiles", action="store_true",
                        help="Skip cross-subreddit user profiling (faster)")
    parser.add_argument("--prompt-only", action="store_true",
                        help="Generate LLM prompt instead of HTML report")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print each HTTP request URL and status code")

    args = parser.parse_args()

    if not args.app_name and not args.user:
        parser.error("Provide either an app name or --user <username>")

    subreddit = args.subreddit
    days = args.days
    output_dir = args.output

    os.makedirs(output_dir, exist_ok=True)

    # Route to user-scan mode
    if args.user:
        _run_user_scan(args)
        return

    app_name = args.app_name

    # File paths
    evidence_path = os.path.join(output_dir, f"{app_name}-Evaluation.csv")
    summary_path = os.path.join(output_dir, f"{app_name}-Evaluation-Summary.csv")
    report_path = os.path.join(output_dir, f"{app_name}-Report.html")
    prompt_path = os.path.join(output_dir, f"{app_name}-Prompt.md")

    # ── Banner ──
    print()
    print("╔══════════════════════════════════════════════╗")
    print("║         macapps-audit · v1.0                 ║")
    print("║   Astroturfing detection for Reddit mods     ║")
    print("╚══════════════════════════════════════════════╝")
    print()
    _print(f"Target: '{app_name}' in r/{subreddit}")
    _print(f"Window: last {days} days")
    _print(f"Output: {output_dir}/")
    print()

    client = RedditClient(verbose=args.verbose)
    start_time = time.time()

    # ── Step 1: Collect mentions from primary subreddit ──
    _print("STEP 1/4 — Collecting mentions from r/{subreddit}...".format(subreddit=subreddit))
    evidence = collect_mentions(client, app_name, subreddit=subreddit,
                                days=days, progress_callback=_print)
    print()

    if not evidence:
        _print("⚠️  No mentions found. Check the app name spelling or try a wider time window.")
        sys.exit(0)

    users = get_unique_users(evidence)
    _print(f"Found {len(evidence)} mentions from {len(users)} unique users")
    print()

    # ── Step 2: Cross-subreddit profiling ──
    if not args.skip_profiles and users:
        _print(f"STEP 2/4 — Profiling {len(users)} users across Reddit...")
        existing_urls = {r["comment_url"] for r in evidence}
        cross_rows = profile_all_users(
            client, users, app_name,
            primary_subreddit=subreddit,
            days=days,
            existing_urls=existing_urls,
            progress_callback=_print,
            verbose=args.verbose,
        )
        evidence.extend(cross_rows)
        print()
    else:
        if args.skip_profiles:
            _print("STEP 2/4 — Skipped (--skip-profiles)")
        else:
            _print("STEP 2/4 — No users to profile")
        print()

    # ── Step 2b: Deduplication ──
    n_dupes = _mark_duplicates(evidence)
    if n_dupes:
        _print(f"  Marked {n_dupes} near-duplicate mention(s) (excluded from scoring)")

    # ── Step 2c: Content validation ──
    n_invalid = _validate_content(evidence, app_name)
    if n_invalid:
        _print(f"  ⚠️  {n_invalid} row(s) do not contain '{app_name}' in comment text (flagged, excluded from scoring)")

    # ── Step 3: Scoring ──
    _print("STEP 3/4 — Computing risk scores...")
    summaries = compute_user_scores(evidence, primary_subreddit=subreddit)

    high_risk = [s for s in summaries if s["risk_level"] in ("High", "Medium-High")]
    _print(f"Scored {len(summaries)} users: {len(high_risk)} flagged as elevated risk")
    print()

    # ── Step 4: Output ──
    _print("STEP 4/4 — Writing output files...")

    write_evidence_csv(evidence, evidence_path)
    _print(f"  📄 {evidence_path} ({len(evidence)} rows)")

    write_summary_csv(summaries, summary_path)
    _print(f"  📄 {summary_path} ({len(summaries)} rows)")

    if args.prompt_only:
        prompt = generate_llm_prompt(app_name, evidence, summaries, subreddit)
        with open(prompt_path, "w", encoding="utf-8") as f:
            f.write(prompt)
        _print(f"  📝 {prompt_path}")
        _print("  → Upload the CSV + prompt to Claude or ChatGPT for detailed analysis")
    else:
        html_report = generate_html_report(
            app_name, evidence, summaries, subreddit,
            days=days, client_stats=client.stats(),
        )
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(html_report)
        _print(f"  🌐 {report_path}")

        # Also generate prompt as bonus
        prompt = generate_llm_prompt(app_name, evidence, summaries, subreddit)
        with open(prompt_path, "w", encoding="utf-8") as f:
            f.write(prompt)
        _print(f"  📝 {prompt_path} (bonus: for deeper LLM analysis)")

    # ── Done ──
    elapsed = time.time() - start_time
    print()
    _print(f"✅ Done in {elapsed:.0f}s · {client.stats()}")
    _print(f"Open {report_path} in your browser to review the report.")
    print()


if __name__ == "__main__":
    main()

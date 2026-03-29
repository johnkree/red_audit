# macapps-audit

Astroturfing detection tool for Reddit moderators. Scans a subreddit for app mentions, profiles users across Reddit, computes risk scores, and generates an HTML report — all without needing a Reddit API key.

## How it works

1. **Collect** — Searches r/macapps (or any subreddit) for all comments and posts mentioning an app name via Reddit's public `.json` endpoints
2. **Profile** — Checks each user's public post history for mentions of the same app in other subreddits
3. **Score** — Computes per-user astroturf probability using heuristics (cross-sub activity, disclosure patterns, text similarity, burst detection, giveaway discounting)
4. **Report** — Generates an HTML report + CSVs + an optional LLM prompt for deeper analysis

## Setup

```fish
# Clone or download this folder
cd macapps-audit

# Install dependencies (just `requests`)
pip install -r requirements.txt
```

Requires Python 3.10+.

## Usage

```fish
# Basic scan (defaults: r/macapps, last 365 days)
python3 macapps_audit.py "FocuSee"

# Custom subreddit and time window
python3 macapps_audit.py "SomeApp" --subreddit macapps --days 180

# Fast mode (skip cross-subreddit profiling)
python3 macapps_audit.py "SomeApp" --skip-profiles

# Generate only the LLM prompt (no HTML report)
python3 macapps_audit.py "SomeApp" --prompt-only

# Open the report when done
open output/SomeApp-Report.html
```

## Output

All files land in `output/` (configurable with `--output`):

| File | Description |
|------|-------------|
| `AppName-Evaluation.csv` | Every verified mention with full text, URLs, dates |
| `AppName-Evaluation-Summary.csv` | Per-user risk scores and rationale |
| `AppName-Report.html` | Self-contained HTML report (open in browser) |
| `AppName-Prompt.md` | Copy-paste prompt for Claude/ChatGPT deep analysis |

## Scoring Rubric

| Score Range | Risk Level | Meaning |
|-------------|-----------|---------|
| 0–15 | Low | Isolated mention or normal discussion |
| 20–40 | Medium | Repeated mentions or mildly suspicious |
| 45–70 | Medium-High | Cross-sub promotion, similar wording, coordination signals |
| 75–95 | High | Strong evidence of coordinated undisclosed promotion |

The scorer looks at: cross-subreddit mention counts, disclosure consistency, temporal burst patterns, text similarity (self and cross-user), giveaway thread discounting, and single-purpose account indicators.

## Limitations

- Only finds what Reddit's search returns (not exhaustive)
- Private/suspended user profiles are skipped gracefully
- Rate-limited to ~10 requests/minute (public endpoint limit)
- A full scan with cross-sub profiling of 15+ users takes 5-10 minutes
- The automated scoring is a starting point — always verify flagged URLs manually

## No API Key Needed

This tool uses Reddit's public `.json` endpoints (append `.json` to any Reddit URL). No OAuth, no developer application, no API key required. It respects rate limits with built-in delays and exponential backoff.

## License

MIT — use it, share it with your mod team, modify it freely.

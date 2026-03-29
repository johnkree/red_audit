"""
Module 4: Reporter
Generates an HTML report from evidence + summary data,
plus a fallback markdown prompt for manual LLM analysis.
"""

import html
from datetime import datetime, timezone


def _esc(text: str) -> str:
    """HTML-escape text."""
    return html.escape(str(text))


def _sentiment_badge(sentiment: str) -> str:
    """Return a colored inline badge for a sentiment value."""
    styles = {
        "positive":   ("color:#6bcb77;", "positive"),
        "negative":   ("color:#ff6b6b;", "negative"),
        "neutral":    ("color:#8b8fa7;", "neutral"),
        "competitor": ("color:#6c8aff;", "competitor"),
    }
    label = sentiment or "neutral"
    style, text = styles.get(label, ("color:#8b8fa7;", label))
    return f'<span style="font-size:0.75rem;font-weight:600;{style}">{text}</span>'


def _notes_cell(notes: str) -> str:
    """Return HTML for the Notes cell, with Own subreddit styled in muted purple."""
    if notes == "Own subreddit":
        return '<span style="color:#9b8fc7;font-size:0.8rem;">Own subreddit</span>'
    return _esc(notes)


def _risk_color(level: str) -> str:
    colors = {
        "High": "#dc2626",
        "Medium-High": "#ea580c",
        "Medium": "#ca8a04",
        "Low": "#16a34a",
    }
    return colors.get(level, "#6b7280")


def _risk_bg(level: str) -> str:
    colors = {
        "High": "#3b1212",
        "Medium-High": "#3b2012",
        "Medium": "#2e2a10",
        "Low": "#0f2a1a",
    }
    return colors.get(level, "#1e2028")


def _overall_verdict(summaries: list[dict]) -> tuple[str, str]:
    """Determine overall verdict and explanation."""
    high = [s for s in summaries if s["risk_level"] == "High"]
    med_high = [s for s in summaries if s["risk_level"] == "Medium-High"]
    med = [s for s in summaries if s["risk_level"] == "Medium"]

    if len(high) >= 2:
        return "Likely Astroturfed", f"{len(high)} accounts show strong astroturfing indicators."
    elif len(high) == 1 and len(med_high) >= 1:
        return "Suspicious", f"1 high-risk account and {len(med_high)} medium-high risk account(s) detected."
    elif len(high) == 1:
        return "Suspicious", "1 high-risk account detected. Warrants investigation."
    elif len(med_high) >= 2:
        return "Suspicious", f"{len(med_high)} accounts with elevated risk scores."
    elif len(med_high) == 1:
        return "Inconclusive", "1 account with some suspicious patterns, but not conclusive."
    elif len(med) >= 3:
        return "Inconclusive", "Several accounts with minor flags. May warrant monitoring."
    elif len(med) >= 1:
        return "Likely Organic", "Minor flags detected but consistent with normal activity."
    else:
        return "Organic", "No suspicious patterns detected."


def _generate_timeline_svg(evidence: list[dict], summaries: list[dict]) -> str:
    """Generate a simple stacked bar chart SVG showing mention activity over time."""
    from collections import defaultdict
    from datetime import datetime, timedelta

    dates = [r["comment_date_text"] for r in evidence if r.get("comment_date_text")]
    if len(dates) < 2:
        return ""

    min_date, max_date = min(dates), max(dates)
    d_start = datetime.strptime(min_date, "%Y-%m-%d")
    d_end   = datetime.strptime(max_date, "%Y-%m-%d")
    total_days = max(1, (d_end - d_start).days + 1)

    # Count per day per user
    day_user: dict = defaultdict(lambda: defaultdict(int))
    for r in evidence:
        d = r.get("comment_date_text", "")
        u = r.get("username", "")
        if d and u:
            day_user[d][u] += 1

    day_totals = {d: sum(v.values()) for d, v in day_user.items()}
    max_total  = max(day_totals.values()) if day_totals else 1

    # Top 8 users by score for coloring
    top_users = [s["username"] for s in summaries[:8]]
    COLORS = ["#6c8aff", "#6bcb77", "#ffd93d", "#ff6b6b",
              "#ffa24e", "#c77dff", "#4cc9f0", "#f72585"]
    user_color = {u: COLORS[i] for i, u in enumerate(top_users)}

    # Layout
    ml, mr, mt, mb = 5, 5, 8, 28
    plot_w, plot_h = 890, 150
    total_w = ml + plot_w + mr
    n_legend_rows = (min(len(top_users), 8) + 3) // 4
    legend_h = n_legend_rows * 20 + 10
    total_h = mt + plot_h + mb + legend_h

    bar_w = max(2, plot_w // total_days - 1)

    bars = ""
    for day, ucounts in sorted(day_user.items()):
        d_obj  = datetime.strptime(day, "%Y-%m-%d")
        day_idx = (d_obj - d_start).days
        x = ml + int(day_idx * plot_w / total_days)
        stack_y = mt + plot_h

        for user in top_users:
            cnt = ucounts.get(user, 0)
            if not cnt:
                continue
            seg_h = max(1, int(cnt / max_total * plot_h))
            stack_y -= seg_h
            color = user_color.get(user, "#8b8fa7")
            bars += f'<rect x="{x}" y="{stack_y}" width="{bar_w}" height="{seg_h}" fill="{color}"/>'

        other = day_totals[day] - sum(ucounts.get(u, 0) for u in top_users)
        if other > 0:
            seg_h = max(1, int(other / max_total * plot_h))
            stack_y -= seg_h
            bars += f'<rect x="{x}" y="{stack_y}" width="{bar_w}" height="{seg_h}" fill="#8b8fa7" opacity="0.5"/>'

    axis_y = mt + plot_h
    axis   = f'<line x1="{ml}" y1="{axis_y}" x2="{ml+plot_w}" y2="{axis_y}" stroke="#2e3348" stroke-width="1"/>'

    mid_date = (d_start + timedelta(days=total_days // 2)).strftime("%Y-%m-%d")
    lbl_y = axis_y + 18
    labels = (
        f'<text x="{ml}" y="{lbl_y}" fill="#8b8fa7" font-size="10" font-family="monospace">{min_date}</text>'
        f'<text x="{ml + plot_w//2}" y="{lbl_y}" fill="#8b8fa7" font-size="10" font-family="monospace" text-anchor="middle">{mid_date}</text>'
        f'<text x="{ml + plot_w}" y="{lbl_y}" fill="#8b8fa7" font-size="10" font-family="monospace" text-anchor="end">{max_date}</text>'
    )

    legend_y0 = mt + plot_h + mb
    legend = ""
    for i, user in enumerate(top_users):
        col, row_ = i % 4, i // 4
        lx = ml + col * 220
        ly = legend_y0 + row_ * 20
        c  = user_color[user]
        legend += f'<rect x="{lx}" y="{ly}" width="9" height="9" rx="2" fill="{c}"/>'
        legend += f'<text x="{lx+13}" y="{ly+8}" fill="#e2e4ed" font-size="10" font-family="sans-serif">u/{user[:22]}</text>'

    return (
        f'<svg width="100%" viewBox="0 0 {total_w} {total_h}" '
        f'xmlns="http://www.w3.org/2000/svg" style="display:block;">'
        f'{axis}{bars}{labels}{legend}</svg>'
    )


def generate_html_report(app_name: str, evidence: list[dict],
                         summaries: list[dict], subreddit: str,
                         days: int, client_stats: str = "") -> str:
    """Generate a self-contained HTML report."""

    now = datetime.now(tz=timezone.utc).strftime("%B %d, %Y")
    total_mentions = len(evidence)
    unique_users = len(summaries)
    subs_spanned = len(set(r["subreddit"] for r in evidence))
    dates = [r["comment_date_text"] for r in evidence if r["comment_date_text"]]
    date_range = f"{min(dates)} – {max(dates)}" if dates else "N/A"

    verdict, verdict_explanation = _overall_verdict(summaries)

    verdict_colors = {
        "Organic": ("#16a34a", "#f0fdf4"),
        "Likely Organic": ("#16a34a", "#f0fdf4"),
        "Inconclusive": ("#ca8a04", "#fefce8"),
        "Suspicious": ("#ea580c", "#fff7ed"),
        "Likely Astroturfed": ("#dc2626", "#fef2f2"),
    }
    v_color, v_bg = verdict_colors.get(verdict, ("#6b7280", "#f9fafb"))

    # Build user rows
    user_rows_html = ""
    for s in summaries:
        rc = _risk_color(s["risk_level"])
        rb = _risk_bg(s["risk_level"])
        top_subs_html = _esc(s.get("top_subreddits", "")).replace("(own)", '<em style="color:#9b8fc7;">(own)</em>')
        user_rows_html += f"""
        <tr style="background:{rb};">
            <td><a href="{_esc(s['profile_url'])}" target="_blank">u/{_esc(s['username'])}</a></td>
            <td><span style="color:{rc};font-weight:700;">{_esc(s['risk_level'])}</span></td>
            <td style="text-align:center;">{s['astroturf_probability_percent']}%</td>
            <td style="text-align:center;">{s['macapps_mentions_visible']}</td>
            <td style="text-align:center;">{s['other_sub_mentions_visible']}</td>
            <td style="text-align:center;">{s.get('own_sub_mentions', 0)}</td>
            <td style="text-align:center;">{s['total_visible_mentions']}</td>
            <td style="text-align:center;">{s['subreddits_spanned']}</td>
            <td class="rationale" style="font-size:0.75rem;">{top_subs_html}</td>
            <td class="rationale" style="font-size:0.75rem;color:#8b8fa7;">{_esc(s.get('sentiment_breakdown', ''))}</td>
            <td class="rationale">{_esc(s['rationale'])}</td>
        </tr>"""

    # Build evidence rows (top 200 for readability, full data in CSV)
    evidence_sorted = sorted(evidence, key=lambda r: r["comment_date_text"], reverse=True)
    evidence_rows_html = ""
    for r in evidence_sorted[:200]:
        reply_icon = '↩' if r.get('is_reply') else ''
        evidence_rows_html += f"""
        <tr>
            <td><a href="https://www.reddit.com/user/{_esc(r['username'])}" target="_blank">u/{_esc(r['username'])}</a></td>
            <td>r/{_esc(r['subreddit'])}</td>
            <td>{_esc(r['comment_date_text'])}</td>
            <td>{_esc(r['source_type'])}</td>
            <td style="text-align:center;color:var(--text-muted);">{reply_icon}</td>
            <td>{_sentiment_badge(r.get('sentiment', 'neutral'))}</td>
            <td class="comment-text">{_esc(r['comment_text'][:300])}</td>
            <td><a href="{_esc(r['comment_url'])}" target="_blank">Link</a></td>
            <td>{_notes_cell(r.get('notes', ''))}</td>
        </tr>"""

    filtered_overflow_note = ""
    if len(evidence) > 200:
        filtered_overflow_note = f'<p class="note">Showing 200 of {len(evidence)} mentions. See Full Evidence section below for all rows.</p>'

    timeline_svg = _generate_timeline_svg(evidence, summaries)

    # Full unfiltered evidence table (all rows, no limit)
    full_evidence_sorted = sorted(evidence, key=lambda r: r["comment_date_text"], reverse=True)
    full_evidence_rows_html = ""
    for r in full_evidence_sorted:
        reply_icon = '↩' if r.get('is_reply') else ''
        full_evidence_rows_html += f"""
        <tr>
            <td><a href="https://www.reddit.com/user/{_esc(r['username'])}" target="_blank">u/{_esc(r['username'])}</a></td>
            <td>r/{_esc(r['subreddit'])}</td>
            <td>{_esc(r['comment_date_text'])}</td>
            <td>{_esc(r['source_type'])}</td>
            <td style="text-align:center;color:var(--text-muted);">{reply_icon}</td>
            <td>{_sentiment_badge(r.get('sentiment', 'neutral'))}</td>
            <td class="comment-text">{_esc(r['comment_text'][:300])}</td>
            <td><a href="{_esc(r['comment_url'])}" target="_blank">Link</a></td>
            <td>{_notes_cell(r.get('notes', ''))}</td>
        </tr>"""

    report_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(app_name)} – Astroturfing Audit Report</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');

:root {{
    --bg: #0f1117;
    --surface: #1a1d27;
    --surface-2: #242836;
    --border: #2e3348;
    --text: #e2e4ed;
    --text-muted: #8b8fa7;
    --accent: #6c8aff;
    --accent-dim: rgba(108, 138, 255, 0.12);
    --red: #ff6b6b;
    --orange: #ffa24e;
    --yellow: #ffd93d;
    --green: #6bcb77;
    --radius: 10px;
}}

* {{ margin: 0; padding: 0; box-sizing: border-box; }}

body {{
    font-family: 'IBM Plex Sans', -apple-system, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    padding: 2rem;
    max-width: 1400px;
    margin: 0 auto;
}}

.header {{
    border-bottom: 1px solid var(--border);
    padding-bottom: 2rem;
    margin-bottom: 2rem;
}}

.header h1 {{
    font-size: 1.75rem;
    font-weight: 700;
    letter-spacing: -0.02em;
    margin-bottom: 0.25rem;
}}

.header .subtitle {{
    color: var(--text-muted);
    font-size: 0.9rem;
}}

.stats-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 1rem;
    margin-bottom: 2rem;
}}

.stat-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1.25rem;
}}

.stat-card .label {{
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    margin-bottom: 0.25rem;
}}

.stat-card .value {{
    font-size: 1.5rem;
    font-weight: 700;
    font-family: 'IBM Plex Mono', monospace;
}}

.verdict-box {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1.5rem;
    margin-bottom: 2rem;
    border-left: 4px solid {v_color};
}}

.verdict-box .verdict-label {{
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    margin-bottom: 0.5rem;
}}

.verdict-box .verdict-value {{
    font-size: 1.25rem;
    font-weight: 700;
    color: {v_color};
    margin-bottom: 0.5rem;
}}

.verdict-box .verdict-detail {{
    color: var(--text-muted);
    font-size: 0.9rem;
}}

section {{
    margin-bottom: 2.5rem;
}}

section h2 {{
    font-size: 1.15rem;
    font-weight: 600;
    margin-bottom: 1rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid var(--border);
}}

table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.85rem;
}}

thead th {{
    background: var(--surface-2);
    color: var(--text-muted);
    font-weight: 600;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding: 0.75rem;
    text-align: left;
    border-bottom: 1px solid var(--border);
    position: sticky;
    top: 0;
    z-index: 10;
}}

tbody td {{
    padding: 0.625rem 0.75rem;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
}}

tbody tr:hover {{
    background: var(--accent-dim);
}}

.rationale {{
    max-width: 400px;
    font-size: 0.8rem;
    color: var(--text-muted);
}}

.comment-text {{
    max-width: 350px;
    font-size: 0.8rem;
    color: var(--text-muted);
    word-break: break-word;
}}

a {{
    color: var(--accent);
    text-decoration: none;
}}

a:hover {{
    text-decoration: underline;
}}

.note {{
    color: var(--text-muted);
    font-size: 0.85rem;
    font-style: italic;
    margin-top: 0.5rem;
}}

.footer {{
    margin-top: 3rem;
    padding-top: 1.5rem;
    border-top: 1px solid var(--border);
    color: var(--text-muted);
    font-size: 0.8rem;
}}

/* Risk level pills for evidence table */
[data-risk="High"] {{ color: var(--red); }}
[data-risk="Medium-High"] {{ color: var(--orange); }}
[data-risk="Medium"] {{ color: var(--yellow); }}
[data-risk="Low"] {{ color: var(--green); }}

/* Responsive */
@media (max-width: 768px) {{
    body {{ padding: 1rem; }}
    .stats-grid {{ grid-template-columns: repeat(2, 1fr); }}
    table {{ font-size: 0.75rem; }}
}}

/* Table wrapper for horizontal scroll */
.table-wrap {{
    overflow-x: auto;
    border: 1px solid var(--border);
    border-radius: var(--radius);
}}
</style>
</head>
<body>

<div class="header">
    <h1>{_esc(app_name)} — Astroturfing Audit</h1>
    <div class="subtitle">Prepared for r/{_esc(subreddit)} moderators · {now}</div>
</div>

<div class="stats-grid">
    <div class="stat-card">
        <div class="label">Total Mentions</div>
        <div class="value">{total_mentions}</div>
    </div>
    <div class="stat-card">
        <div class="label">Unique Users</div>
        <div class="value">{unique_users}</div>
    </div>
    <div class="stat-card">
        <div class="label">Subreddits</div>
        <div class="value">{subs_spanned}</div>
    </div>
    <div class="stat-card">
        <div class="label">Date Range</div>
        <div class="value" style="font-size:0.95rem;">{date_range}</div>
    </div>
    <div class="stat-card">
        <div class="label">Time Window</div>
        <div class="value" style="font-size:0.95rem;">{days} days</div>
    </div>
</div>

<div class="verdict-box">
    <div class="verdict-label">Overall Verdict</div>
    <div class="verdict-value">{verdict}</div>
    <div class="verdict-detail">{verdict_explanation}</div>
</div>

{f'<section><h2>Activity Timeline</h2><div style="background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:1rem;">{timeline_svg}</div></section>' if timeline_svg else ''}

<section>
    <h2>User Risk Assessment</h2>
    <div class="table-wrap">
    <table>
        <thead>
            <tr>
                <th>User</th>
                <th>Risk</th>
                <th>Score</th>
                <th>r/{_esc(subreddit)}</th>
                <th>Cross-Sub</th>
                <th>Own Sub</th>
                <th>Total</th>
                <th>Subs</th>
                <th>Top Subreddits</th>
                <th>Sentiment</th>
                <th>Rationale</th>
            </tr>
        </thead>
        <tbody>
            {user_rows_html}
        </tbody>
    </table>
    </div>
</section>

<section>
    <h2>Evidence Log <span style="color:var(--text-muted);font-size:0.85rem;font-weight:400;">(scored mentions, max 200)</span></h2>
    {filtered_overflow_note}
    <div class="table-wrap">
    <table>
        <thead>
            <tr>
                <th>User</th>
                <th>Subreddit</th>
                <th>Date</th>
                <th>Type</th>
                <th>Reply?</th>
                <th>Sentiment</th>
                <th>Comment Text</th>
                <th>URL</th>
                <th>Notes</th>
            </tr>
        </thead>
        <tbody>
            {evidence_rows_html}
        </tbody>
    </table>
    </div>
</section>

<section>
    <h2>Full Evidence <span style="color:var(--text-muted);font-size:0.85rem;font-weight:400;">(all {len(evidence)} rows — unfiltered, verify sentiment tags here)</span></h2>
    <div class="table-wrap">
    <table>
        <thead>
            <tr>
                <th>User</th>
                <th>Subreddit</th>
                <th>Date</th>
                <th>Type</th>
                <th>Reply?</th>
                <th>Sentiment</th>
                <th>Comment Text</th>
                <th>URL</th>
                <th>Notes</th>
            </tr>
        </thead>
        <tbody>
            {full_evidence_rows_html}
        </tbody>
    </table>
    </div>
</section>

<div class="footer">
    <p>Generated by macapps-audit · {client_stats}</p>
    <p>This is an automated assessment. Always verify flagged evidence by clicking the URLs before taking moderator action.</p>
</div>

</body>
</html>"""

    return report_html


def generate_user_html_report(username: str, rows: list[dict],
                              summary: dict, days: int,
                              client_stats: str = "") -> str:
    """Generate a self-contained HTML report for a single-user shill scan."""
    from collections import Counter

    now = datetime.now(tz=timezone.utc).strftime("%B %d, %Y")
    score = summary["astroturf_probability_percent"]
    risk = summary["risk_level"]
    rc = {
        "High": "#dc2626", "Medium-High": "#ea580c",
        "Medium": "#ca8a04", "Low": "#16a34a",
    }.get(risk, "#6b7280")

    verdict_map = {
        "High": ("Likely Shill", "Strong indicators of undisclosed promotion detected."),
        "Medium-High": ("Suspicious", "Elevated promotion patterns, warrants investigation."),
        "Medium": ("Inconclusive", "Some promotional patterns, but not conclusive."),
        "Low": ("Likely Organic", "No significant shill indicators found."),
    }
    verdict, verdict_explanation = verdict_map.get(risk, ("Unknown", ""))

    # Subreddit breakdown
    sub_counter: Counter = Counter(r["subreddit"] for r in rows)
    sub_rows_html = ""
    for sub, count in sub_counter.most_common(30):
        pct = int(count / len(rows) * 100) if rows else 0
        sub_rows_html += f"""
        <tr>
            <td><a href="https://www.reddit.com/r/{_esc(sub)}" target="_blank">r/{_esc(sub)}</a></td>
            <td style="text-align:center;">{count}</td>
            <td style="text-align:center;">{pct}%</td>
        </tr>"""

    # Evidence rows
    rows_sorted = sorted(rows, key=lambda r: r["comment_date_text"], reverse=True)
    evidence_rows_html = ""
    for r in rows_sorted[:200]:
        evidence_rows_html += f"""
        <tr>
            <td>r/{_esc(r['subreddit'])}</td>
            <td>{_esc(r['comment_date_text'])}</td>
            <td>{_esc(r['source_type'])}</td>
            <td class="comment-text">{_esc(r['comment_text'][:300])}</td>
            <td><a href="{_esc(r['comment_url'])}" target="_blank">Link</a></td>
        </tr>"""

    overflow_note = ""
    if len(rows) > 200:
        overflow_note = f'<p class="note">Showing 200 of {len(rows)} posts. Full data in CSV.</p>'

    top_product = _esc(summary.get("top_mentioned_product", "") or "–")
    concentration = summary.get("product_concentration_percent", 0)
    dates = [r["comment_date_text"] for r in rows if r["comment_date_text"]]
    date_range = f"{min(dates)} – {max(dates)}" if dates else "N/A"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>u/{_esc(username)} — Shill Analysis</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');
:root {{
    --bg: #0f1117; --surface: #1a1d27; --surface-2: #242836;
    --border: #2e3348; --text: #e2e4ed; --text-muted: #8b8fa7;
    --accent: #6c8aff; --accent-dim: rgba(108,138,255,0.12);
    --radius: 10px;
}}
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:'IBM Plex Sans',-apple-system,sans-serif; background:var(--bg); color:var(--text); line-height:1.6; padding:2rem; max-width:1400px; margin:0 auto; }}
.header {{ border-bottom:1px solid var(--border); padding-bottom:2rem; margin-bottom:2rem; }}
.header h1 {{ font-size:1.75rem; font-weight:700; letter-spacing:-0.02em; margin-bottom:0.25rem; }}
.header .subtitle {{ color:var(--text-muted); font-size:0.9rem; }}
.stats-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:1rem; margin-bottom:2rem; }}
.stat-card {{ background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:1.25rem; }}
.stat-card .label {{ font-size:0.75rem; text-transform:uppercase; letter-spacing:0.05em; color:var(--text-muted); margin-bottom:0.25rem; }}
.stat-card .value {{ font-size:1.5rem; font-weight:700; font-family:'IBM Plex Mono',monospace; }}
.verdict-box {{ background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:1.5rem; margin-bottom:2rem; border-left:4px solid {rc}; }}
.verdict-box .verdict-label {{ font-size:0.75rem; text-transform:uppercase; letter-spacing:0.05em; color:var(--text-muted); margin-bottom:0.5rem; }}
.verdict-box .verdict-value {{ font-size:1.25rem; font-weight:700; color:{rc}; margin-bottom:0.5rem; }}
.verdict-box .verdict-detail {{ color:var(--text-muted); font-size:0.9rem; }}
.rationale-box {{ background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:1.25rem; margin-bottom:2rem; font-size:0.9rem; color:var(--text-muted); }}
section {{ margin-bottom:2.5rem; }}
section h2 {{ font-size:1.15rem; font-weight:600; margin-bottom:1rem; padding-bottom:0.5rem; border-bottom:1px solid var(--border); }}
table {{ width:100%; border-collapse:collapse; font-size:0.85rem; }}
thead th {{ background:var(--surface-2); color:var(--text-muted); font-weight:600; font-size:0.75rem; text-transform:uppercase; letter-spacing:0.04em; padding:0.75rem; text-align:left; border-bottom:1px solid var(--border); position:sticky; top:0; z-index:10; }}
tbody td {{ padding:0.625rem 0.75rem; border-bottom:1px solid var(--border); vertical-align:top; }}
tbody tr:hover {{ background:var(--accent-dim); }}
.comment-text {{ max-width:400px; font-size:0.8rem; color:var(--text-muted); word-break:break-word; }}
a {{ color:var(--accent); text-decoration:none; }}
a:hover {{ text-decoration:underline; }}
.note {{ color:var(--text-muted); font-size:0.85rem; font-style:italic; margin-top:0.5rem; }}
.footer {{ margin-top:3rem; padding-top:1.5rem; border-top:1px solid var(--border); color:var(--text-muted); font-size:0.8rem; }}
.table-wrap {{ overflow-x:auto; border:1px solid var(--border); border-radius:var(--radius); }}
@media (max-width:768px) {{ body {{ padding:1rem; }} .stats-grid {{ grid-template-columns:repeat(2,1fr); }} }}
</style>
</head>
<body>

<div class="header">
    <h1>u/{_esc(username)} — Shill Analysis</h1>
    <div class="subtitle">Last {days} days · {date_range} · Generated {now}</div>
</div>

<div class="stats-grid">
    <div class="stat-card">
        <div class="label">Posts Scanned</div>
        <div class="value">{len(rows)}</div>
    </div>
    <div class="stat-card">
        <div class="label">Subreddits</div>
        <div class="value">{summary['unique_subreddits']}</div>
    </div>
    <div class="stat-card">
        <div class="label">Risk Score</div>
        <div class="value" style="color:{rc};">{score}%</div>
    </div>
    <div class="stat-card">
        <div class="label">Top Product</div>
        <div class="value" style="font-size:1rem;">{top_product}</div>
    </div>
    <div class="stat-card">
        <div class="label">Concentration</div>
        <div class="value">{concentration}%</div>
    </div>
</div>

<div class="verdict-box">
    <div class="verdict-label">Verdict</div>
    <div class="verdict-value">{verdict}</div>
    <div class="verdict-detail">{verdict_explanation}</div>
</div>

<div class="rationale-box">
    <strong>Signal breakdown:</strong> {_esc(summary['rationale'])}
</div>

<section>
    <h2>Activity by Subreddit</h2>
    <div class="table-wrap">
    <table>
        <thead><tr><th>Subreddit</th><th>Posts</th><th>% of Activity</th></tr></thead>
        <tbody>{sub_rows_html}</tbody>
    </table>
    </div>
</section>

<section>
    <h2>Activity Log</h2>
    {overflow_note}
    <div class="table-wrap">
    <table>
        <thead>
            <tr><th>Subreddit</th><th>Date</th><th>Type</th><th>Text</th><th>URL</th></tr>
        </thead>
        <tbody>{evidence_rows_html}</tbody>
    </table>
    </div>
</section>

<div class="footer">
    <p>Generated by macapps-audit · {client_stats}</p>
    <p>Automated assessment only. Always verify evidence before taking moderator action.</p>
</div>

</body>
</html>"""


def generate_llm_prompt(app_name: str, evidence: list[dict],
                        summaries: list[dict], subreddit: str) -> str:
    """
    Generate a copy-paste-ready prompt for manual LLM analysis.
    Includes the summary data as context.
    """
    summary_text = "USER SUMMARY DATA:\n"
    for s in summaries:
        summary_text += (
            f"- u/{s['username']}: {s['total_visible_mentions']} mentions, "
            f"{s['subreddits_spanned']} subs, score={s['astroturf_probability_percent']}%, "
            f"risk={s['risk_level']}, rationale: {s['rationale']}\n"
        )

    prompt = f"""You are an experienced Reddit community analyst helping moderators of r/{subreddit} detect astroturfing and coordinated promotion. I've run an automated audit of "{app_name}" mentions.

Below is a pre-computed risk summary, followed by the full evidence CSV (uploaded separately).

{summary_text}

Please review the CSV file I'm uploading alongside this prompt and produce a report with these sections:

**1. Overview**
What app is being analyzed, how many mentions, unique users, subreddits, and date range.

**2. Key Findings**
The most important patterns, as a bulleted list. Each finding must include a specific URL and a short quote from the data. Look for:
- Same user recommending the app across many subreddits
- Suspiciously similar wording between different users
- Accounts that only exist to promote this app
- Clusters of mentions around the same dates
- Signs of undisclosed developer or affiliate connections

**3. User-by-User Assessment**
A table sorted from highest risk to lowest:

| Username | Risk Level | Mentions | Subreddits | Summary | Key Evidence |
|----------|-----------|----------|------------|---------|-------------|

**4. Giveaway and Promo Thread Notes**
List any mentions from giveaway or promotional threads.

**5. Overall Verdict**
One of: Organic / Likely Organic / Inconclusive / Suspicious / Likely Astroturfed. Explain in 2-4 sentences.

**6. Recommended Actions**
0-3 concrete next steps.

Important rules:
- Transparent developer participation is normal. Only flag hidden connections.
- Discount giveaway-thread praise.
- Cite specific URLs and quote comment text for every claim.
- Be fair. People genuinely recommend apps they like.
"""
    return prompt

"""
fetch_jobs.py
Runs on a schedule via GitHub Actions.
Fetches GTA PM jobs from JSearch (RapidAPI), scores them against
Hani Juzer's profile, and writes index.html to the repo root.
"""

import json
import os
import sys
import http.client
from datetime import datetime, timezone
from pathlib import Path

# ── CONFIG ────────────────────────────────────────────────────────────────────
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "")
if not RAPIDAPI_KEY:
    sys.exit("ERROR: RAPIDAPI_KEY environment variable is not set.")

SEARCH_QUERIES = [
    "Project Manager construction",
    "Assistant Project Manager infrastructure",
    "Project Coordinator civil engineering",
    "Project Scheduler Primavera P6",
]

# ── SCORING WEIGHTS ───────────────────────────────────────────────────────────
POSITIVE_KEYWORDS = {
    # High value (2 pts each)
    "pmp": 2, "primavera": 2, "p6": 2, "lrt": 2, "metrolinx": 2,
    "transit": 2, "light rail": 2, "eglinton": 2, "crosslinx": 2,
    "evm": 2, "earned value": 2, "infrastructure": 2,
    # Medium value (1 pt each)
    "project manager": 1, "construction": 1, "civil": 1,
    "scheduling": 1, "ms project": 1, "change order": 1,
    "cost control": 1, "stakeholder": 1, "risk management": 1,
    "design-build": 1, "design build": 1, "commissioning": 1,
    "as-built": 1, "procurement": 1, "contract management": 1,
    "power bi": 1, "autocad": 1, "revit": 1, "municipal": 1,
    "industrial": 1, "multi-disciplinary": 1,
}

NEGATIVE_KEYWORDS = {
    "software engineer": -3, "developer": -3, "marketing": -3,
    "sales": -2, "accounting": -2, "nurse": -3, "teacher": -3,
    "mining": -1, "nuclear": -1, "offshore": -2,
}

SALARY_BOOST = {
    # keyword → bonus score
    "director": -5,   # likely overqualified / stretch
    "vp ": -5,
    "junior": -5,
    "entry": -5,
    "coordinator": 0,  # neutral — still relevant
}


# ── JSearch API CALL ──────────────────────────────────────────────────────────
def fetch_jobs_for_query(query: str) -> list[dict]:
    import urllib.parse
    conn = http.client.HTTPSConnection("jsearch.p.rapidapi.com")
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "jsearch.p.rapidapi.com",
    }
    # Embed location in query for best JSearch results
    full_query = f"{query} Toronto Ontario Canada"
    encoded = urllib.parse.quote(full_query)
    path = f"/search?query={encoded}&date_posted=month&num_pages=2&page=1&country=ca"
    conn.request("GET", path, headers=headers)
    res = conn.getresponse()
    raw = res.read()
    print(f"    HTTP {res.status} ({len(raw)} bytes)")
    try:
        data = json.loads(raw)
        if data.get("status") != "OK":
            print(f"    API error: {data.get('message', data.get('status', 'unknown'))}")
        return data.get("data", [])
    except Exception as e:
        print(f"  Warning: could not parse response for '{query}': {e}")
        print(f"  Raw: {raw[:200]}")
        return []


# ── SCORE A JOB ───────────────────────────────────────────────────────────────
def score_job(job: dict) -> int:
    text = " ".join([
        (job.get("job_title") or ""),
        (job.get("job_description") or ""),
        (job.get("employer_name") or ""),
    ]).lower()

    score = 50  # base

    for kw, pts in POSITIVE_KEYWORDS.items():
        if kw in text:
            score += pts

    for kw, pts in NEGATIVE_KEYWORDS.items():
        if kw in text:
            score += pts

    for kw, pts in SALARY_BOOST.items():
        if kw in text:
            score += pts

    # Salary bonus
    min_sal = job.get("job_min_salary") or 0
    if min_sal >= 100000:
        score += 5
    elif min_sal >= 80000:
        score += 3

    # Remote penalty (field roles need on-site)
    if job.get("job_is_remote"):
        score -= 5

    return max(0, min(100, score))


def tier(score: int) -> int:
    if score >= 75:
        return 1
    if score >= 60:
        return 2
    return 3


def fmt_salary(job: dict) -> str:
    mn = job.get("job_min_salary")
    mx = job.get("job_max_salary")
    period = (job.get("job_salary_period") or "").lower()
    if not mn and not mx:
        return ""
    def fmt(v):
        if not v:
            return ""
        v = int(v)
        if period in ("year", "annual", "yearly"):
            return f"${v:,}"
        if period == "hour":
            return f"${v}/hr"
        return f"${v:,}"
    parts = [p for p in [fmt(mn), fmt(mx)] if p]
    if len(parts) == 2:
        return " – ".join(parts)
    return parts[0] if parts else ""


# ── DEDUPLICATE ───────────────────────────────────────────────────────────────
def dedup(jobs: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for j in jobs:
        key = f"{(j.get('job_title') or '').lower().strip()}|{(j.get('employer_name') or '').lower().strip()}"
        if key not in seen:
            seen.add(key)
            out.append(j)
    return out


# ── HTML GENERATION ───────────────────────────────────────────────────────────
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GTA PM Job Search — Hani Juzer</title>
<style>
  :root{{
    --navy:#0D1F3C;--accent:#E8A020;--accentL:#FEF3C7;
    --teal:#0E7490;--tealL:#CFFAFE;--bg:#F0F4F8;--card:#FFFFFF;
    --g1c:#065F46;--g1b:#D1FAE5;--g2c:#92400E;--g2b:#FEF3C7;
    --g3c:#1E40AF;--g3b:#DBEAFE;--muted:#64748B;--border:#E2E8F0;
  }}
  *{{box-sizing:border-box;}}
  body{{margin:0;font-family:'Inter',-apple-system,BlinkMacSystemFont,sans-serif;background:var(--bg);color:#1E293B;}}
  .header{{background:var(--navy);color:#fff;padding:20px 32px;}}
  .header h1{{margin:0;font-size:22px;font-weight:800;letter-spacing:-0.02em;}}
  .header h1 span{{color:var(--accent);}}
  .header p{{margin:4px 0 0;font-size:13px;color:#94A3B8;}}
  .update-badge{{display:inline-block;background:var(--g1b);color:var(--g1c);font-size:11px;font-weight:700;padding:3px 10px;border-radius:99px;margin-top:8px;}}
  .nav{{background:var(--card);border-bottom:1px solid var(--border);padding:0 32px;display:flex;gap:2px;overflow-x:auto;}}
  .nav button{{padding:12px 16px;font-size:13px;font-weight:600;cursor:pointer;background:none;border:none;white-space:nowrap;border-bottom:3px solid transparent;color:var(--muted);margin-bottom:-1px;font-family:inherit;}}
  .nav button.active{{border-bottom:3px solid var(--accent);color:var(--navy);}}
  .container{{max-width:1080px;margin:0 auto;padding:28px 24px;}}
  .tabpanel{{display:none;}} .tabpanel.active{{display:block;}}
  .grid-gap{{display:grid;gap:20px;}}
  .card{{background:var(--card);border-radius:12px;border:1px solid var(--border);padding:20px 24px;box-shadow:0 1px 4px rgba(0,0,0,0.05);}}
  .section-head{{margin:0 0 14px;font-size:11px;font-weight:800;letter-spacing:0.1em;text-transform:uppercase;color:var(--teal);}}
  .bar{{background:var(--border);border-radius:99px;height:7px;overflow:hidden;}}
  .bar-fill{{height:100%;border-radius:99px;}}
  .score{{font-weight:800;font-size:12px;padding:2px 10px;border-radius:99px;border:1px solid;}}
  .score.high{{background:var(--g1b);color:var(--g1c);border-color:#065F4644;}}
  .score.med{{background:var(--g2b);color:var(--g2c);border-color:#92400E44;}}
  .score.low{{background:var(--g3b);color:var(--g3c);border-color:#1E40AF44;}}
  .tier-tag{{font-weight:700;font-size:11px;padding:2px 9px;border-radius:5px;border:1px solid;}}
  .tier-tag.t1{{background:var(--g1b);color:var(--g1c);border-color:#065F4633;}}
  .tier-tag.t2{{background:var(--g2b);color:var(--g2c);border-color:#92400E33;}}
  .tier-tag.t3{{background:var(--g3b);color:var(--g3c);border-color:#1E40AF33;}}
  .jobs-toolbar{{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;flex-wrap:wrap;gap:8px;}}
  .jobs-toolbar h3{{margin:0;font-size:16px;font-weight:700;color:var(--navy);}}
  .job-card{{margin-bottom:10px;}}
  .job-top{{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;}}
  .job-info{{flex:1;}}
  .job-title-row{{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:4px;}}
  .job-rank{{background:var(--navy);color:var(--accent);font-size:11px;font-weight:800;width:24px;height:24px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;flex-shrink:0;}}
  .job-title{{font-weight:700;font-size:15px;color:var(--navy);}}
  .job-meta{{margin:0;font-size:13px;color:var(--muted);}}
  .job-right{{text-align:right;flex-shrink:0;}}
  .toggle-btn{{margin-top:6px;font-size:12px;color:var(--teal);background:none;border:none;cursor:pointer;font-weight:700;font-family:inherit;display:block;}}
  .job-details{{margin-top:14px;padding-top:14px;border-top:1px solid var(--border);display:none;}}
  .job-card.open .job-details{{display:block;}}
  .desc-box{{font-size:13px;color:#374151;line-height:1.7;max-height:200px;overflow-y:auto;background:var(--bg);padding:12px 14px;border-radius:8px;margin-bottom:14px;white-space:pre-wrap;}}
  .links-row{{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px;}}
  .btn-apply{{padding:8px 18px;background:var(--accent);color:var(--navy);font-weight:800;font-size:13px;border-radius:8px;text-decoration:none;}}
  .btn-company{{padding:8px 18px;border:1.5px solid var(--border);color:var(--navy);font-weight:600;font-size:13px;border-radius:8px;text-decoration:none;}}
  .kpi-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;}}
  .kpi-card{{text-align:center;padding:16px 12px;}}
  .kpi-card .icon{{font-size:26px;}}
  .kpi-card .val{{font-size:30px;font-weight:800;color:var(--navy);margin:4px 0;}}
  .kpi-card .lbl{{font-size:11px;color:var(--muted);font-weight:600;}}
  .strengths-grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px;}}
  .strength-item{{background:var(--g1b);border-radius:8px;padding:12px 14px;border-left:3px solid var(--g1c);}}
  .strength-item p.t{{margin:0 0 4px;font-weight:700;font-size:13px;color:var(--g1c);}}
  .strength-item p.n{{margin:0;font-size:12px;color:#374151;line-height:1.5;}}
  table{{width:100%;border-collapse:collapse;font-size:13px;}}
  thead tr{{background:var(--navy);color:#fff;}}
  th{{padding:8px 12px;text-align:left;font-size:12px;font-weight:700;}}
  td{{padding:9px 12px;}}
  tbody tr{{border-bottom:1px solid var(--border);}}
  tbody tr:nth-child(even){{background:var(--bg);}}
  tbody tr:nth-child(odd){{background:var(--card);}}
  .urgency{{padding:2px 9px;border-radius:99px;font-size:11px;font-weight:700;}}
  .u-High{{background:#FEE2E2;color:#991B1B;}}
  .u-Medium{{background:var(--g2b);color:var(--g2c);}}
  .u-Low{{background:var(--g3b);color:var(--g3c);}}
  .prob{{padding:2px 9px;border-radius:99px;font-size:11px;font-weight:700;}}
  .p-VeryHigh{{background:var(--g1b);color:var(--g1c);}}
  .p-High{{background:var(--tealL);color:var(--teal);}}
  .p-Moderate{{background:var(--g2b);color:var(--g2c);}}
  .readiness-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;}}
  .r-item{{text-align:center;}}
  .r-item .num{{font-size:28px;font-weight:800;}}
  .r-item .lbl{{font-size:12px;color:var(--muted);font-weight:600;}}
  .two-col{{display:grid;grid-template-columns:1fr 1fr;gap:20px;}}
  .plan-row{{display:flex;gap:12px;margin-bottom:10px;align-items:flex-start;}}
  .plan-day{{font-weight:800;font-size:11px;padding:3px 8px;border-radius:6px;flex-shrink:0;}}
  .d-apply{{background:var(--g1b);color:var(--g1c);}}
  .d-network{{background:var(--tealL);color:var(--teal);}}
  .d-prep{{background:var(--accentL);color:var(--g2c);}}
  .plan-footer{{margin-top:14px;padding:10px 14px;background:var(--bg);border-radius:8px;font-size:12px;color:var(--muted);}}
  .rec-row{{display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid var(--border);}}
  .rec-row:last-of-type{{border-bottom:none;}}
  .rec-row .name{{margin:0;font-weight:700;font-size:13px;color:var(--navy);}}
  .rec-row .focus{{margin:2px 0 0;font-size:12px;color:var(--muted);}}
  .rec-row a{{font-size:12px;color:var(--teal);font-weight:700;text-decoration:none;}}
  .industry-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;}}
  .ind-item{{background:var(--bg);border-radius:8px;padding:12px 14px;}}
  .ind-row{{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;}}
  .ind-row span:first-child{{font-weight:700;font-size:13px;color:var(--navy);}}
  .ind-row span:last-child{{font-weight:800;font-size:13px;color:var(--teal);}}
  .ind-note{{margin:6px 0 0;font-size:11px;color:var(--muted);}}
  .no-jobs{{text-align:center;padding:40px;color:var(--muted);font-size:15px;}}
  @media(max-width:760px){{
    .strengths-grid,.two-col,.readiness-grid,.industry-grid,.kpi-grid{{grid-template-columns:1fr;}}
  }}
</style>
</head>
<body>

<div class="header">
  <h1><span>GTA</span> Project Management Job Search</h1>
  <p>Hani Juzer, M.E, PMP, EIT &nbsp;·&nbsp; Toronto, ON</p>
  <span class="update-badge">🔄 Auto-updated: {updated_at}</span>
</div>

<div class="nav" id="nav">
  <button class="active" data-tab="overview">📋 Resume Analysis</button>
  <button data-tab="jobs">🎯 Live Jobs ({total})</button>
  <button data-tab="t1">🟢 Tier 1 ({t1count})</button>
  <button data-tab="t2">🟡 Tier 2 ({t2count})</button>
  <button data-tab="t3">🔵 Tier 3 ({t3count})</button>
  <button data-tab="dashboard">📊 Dashboard</button>
</div>

<div class="container">

  <!-- OVERVIEW -->
  <div class="tabpanel active grid-gap" id="overview">
    <div class="card">
      <h3 class="section-head">Professional Strengths &amp; Competitive Advantages</h3>
      <div class="strengths-grid">
        <div class="strength-item"><p class="t">✓ PMP + EIT Certified</p><p class="n">Dual credentials are highly competitive in GTA; fewer than 20% of PMs hold both.</p></div>
        <div class="strength-item"><p class="t">✓ 10+ Years PM Experience</p><p class="n">Spans structural, industrial, municipal infrastructure, and transit — rare breadth.</p></div>
        <div class="strength-item"><p class="t">✓ Eglinton Crosstown LRT</p><p class="n">Live mega-project experience is a top signal for Metrolinx, TTC, and transit contractors.</p></div>
        <div class="strength-item"><p class="t">✓ EVM Proficiency (SV, CV, SPI)</p><p class="n">Earned Value metrics are mandatory for most public-sector and P3 roles.</p></div>
        <div class="strength-item"><p class="t">✓ Primavera P6 + MS Project</p><p class="n">Both tools listed — covers 95%+ of GTA scheduling requirements.</p></div>
        <div class="strength-item"><p class="t">✓ Design-Build &amp; Multi-Disciplinary</p><p class="n">Arabian House decade shows delivery across civil, structural, MEP coordination.</p></div>
        <div class="strength-item"><p class="t">✓ M.E. Civil Engineering</p><p class="n">Graduate degree separates you from diploma-only PMs when competing for senior roles.</p></div>
      </div>
    </div>
    <div class="card">
      <h3 class="section-head">Skills Gap Analysis</h3>
      <table>
        <thead><tr><th>Missing Skill / Credential</th><th>Urgency</th><th>Why It Matters</th></tr></thead>
        <tbody>
          <tr><td style="font-weight:600;color:var(--navy)">P.Eng. (Ontario)</td><td><span class="urgency u-High">High</span></td><td>EIT status is a stepping stone — PEO licensure unlocks 'Engineering PM' titles.</td></tr>
          <tr><td style="font-weight:600;color:var(--navy)">Procore / Autodesk Construction Cloud</td><td><span class="urgency u-High">High</span></td><td>Appears in ~60% of GTA construction PM postings; not listed on resume.</td></tr>
          <tr><td style="font-weight:600;color:var(--navy)">LEED / Sustainability Credential</td><td><span class="urgency u-Medium">Medium</span></td><td>Increasingly requested by developers and municipalities.</td></tr>
          <tr><td style="font-weight:600;color:var(--navy)">Oracle Primavera Cloud / EPPM</td><td><span class="urgency u-Medium">Medium</span></td><td>Cloud scheduling tools are replacing on-prem P6 at larger firms.</td></tr>
          <tr><td style="font-weight:600;color:var(--navy)">BIM Coordination Experience</td><td><span class="urgency u-Medium">Medium</span></td><td>Revit is listed but BIM coordination / clash detection not highlighted.</td></tr>
          <tr><td style="font-weight:600;color:var(--navy)">FIDIC / NEC Contract Knowledge</td><td><span class="urgency u-Low">Low</span></td><td>Beneficial for P3 and infrastructure programs.</td></tr>
        </tbody>
      </table>
    </div>
    <div class="card">
      <h3 class="section-head">Market Positioning — GTA Salary &amp; Probability by Role</h3>
      <table>
        <thead><tr><th>Target Role</th><th>Career Level</th><th>Expected Salary (GTA)</th><th>Success Probability</th></tr></thead>
        <tbody>
          <tr><td style="font-weight:600;color:var(--navy)">Assistant Project Manager</td><td style="color:var(--muted)">Senior</td><td style="font-weight:700;color:var(--teal)">$90k – $115k</td><td><span class="prob p-VeryHigh">Very High</span></td></tr>
          <tr><td style="font-weight:600;color:var(--navy)">Project Manager</td><td style="color:var(--muted)">Senior</td><td style="font-weight:700;color:var(--teal)">$110k – $145k</td><td><span class="prob p-High">High</span></td></tr>
          <tr><td style="font-weight:600;color:var(--navy)">Construction Project Manager</td><td style="color:var(--muted)">Senior</td><td style="font-weight:700;color:var(--teal)">$115k – $155k</td><td><span class="prob p-High">High</span></td></tr>
          <tr><td style="font-weight:600;color:var(--navy)">Project Coordinator</td><td style="color:var(--muted)">Lead</td><td style="font-weight:700;color:var(--teal)">$75k – $95k</td><td><span class="prob p-VeryHigh">Very High</span></td></tr>
          <tr><td style="font-weight:600;color:var(--navy)">Project Controls Coordinator</td><td style="color:var(--muted)">Intermediate–Senior</td><td style="font-weight:700;color:var(--teal)">$85k – $115k</td><td><span class="prob p-High">High</span></td></tr>
          <tr><td style="font-weight:600;color:var(--navy)">Project Scheduler</td><td style="color:var(--muted)">Senior</td><td style="font-weight:700;color:var(--teal)">$90k – $120k</td><td><span class="prob p-High">High</span></td></tr>
        </tbody>
      </table>
    </div>
    <div class="card">
      <h3 class="section-head">Role Readiness Assessment (out of 10)</h3>
      <div class="readiness-grid">
        <div class="r-item"><div class="num" style="color:var(--g1c)">10/10</div><div class="lbl">Assistant PM</div><div class="bar" style="margin-top:6px"><div class="bar-fill" style="width:100%;background:var(--g1c)"></div></div></div>
        <div class="r-item"><div class="num" style="color:var(--g1c)">9/10</div><div class="lbl">Project Manager</div><div class="bar" style="margin-top:6px"><div class="bar-fill" style="width:90%;background:var(--g1c)"></div></div></div>
        <div class="r-item"><div class="num" style="color:var(--g1c)">9/10</div><div class="lbl">Construction PM</div><div class="bar" style="margin-top:6px"><div class="bar-fill" style="width:90%;background:var(--g1c)"></div></div></div>
        <div class="r-item"><div class="num" style="color:var(--g1c)">10/10</div><div class="lbl">Project Coordinator</div><div class="bar" style="margin-top:6px"><div class="bar-fill" style="width:100%;background:var(--g1c)"></div></div></div>
        <div class="r-item"><div class="num" style="color:var(--teal)">8/10</div><div class="lbl">Project Controls</div><div class="bar" style="margin-top:6px"><div class="bar-fill" style="width:80%;background:var(--teal)"></div></div></div>
        <div class="r-item"><div class="num" style="color:var(--teal)">8/10</div><div class="lbl">Scheduler</div><div class="bar" style="margin-top:6px"><div class="bar-fill" style="width:80%;background:var(--teal)"></div></div></div>
        <div class="r-item"><div class="num" style="color:var(--accent)">7/10</div><div class="lbl">Program Coordinator</div><div class="bar" style="margin-top:6px"><div class="bar-fill" style="width:70%;background:var(--accent)"></div></div></div>
        <div class="r-item"><div class="num" style="color:var(--teal)">8/10</div><div class="lbl">Ops PM</div><div class="bar" style="margin-top:6px"><div class="bar-fill" style="width:80%;background:var(--teal)"></div></div></div>
      </div>
    </div>
  </div>

  <!-- ALL JOBS -->
  <div class="tabpanel" id="jobs">
    <div class="jobs-toolbar">
      <h3>Live GTA PM Jobs — {total} Found · Sorted by Fit Score</h3>
      <div style="font-size:12px;color:var(--muted);display:flex;gap:12px;">
        <span style="color:var(--g1c)">🟢 ≥75 High</span>
        <span style="color:var(--g2c)">🟡 60–74 Medium</span>
        <span style="color:var(--g3c)">🔵 &lt;60 Stretch</span>
      </div>
    </div>
    {all_jobs_html}
  </div>

  <!-- TIER 1 -->
  <div class="tabpanel" id="t1">
    <div class="jobs-toolbar"><h3>🟢 Tier 1 — High Probability ({t1count} jobs)</h3></div>
    {t1_jobs_html}
  </div>

  <!-- TIER 2 -->
  <div class="tabpanel" id="t2">
    <div class="jobs-toolbar"><h3>🟡 Tier 2 — Medium Probability ({t2count} jobs)</h3></div>
    {t2_jobs_html}
  </div>

  <!-- TIER 3 -->
  <div class="tabpanel" id="t3">
    <div class="jobs-toolbar"><h3>🔵 Tier 3 — Stretch Opportunities ({t3count} jobs)</h3></div>
    {t3_jobs_html}
  </div>

  <!-- DASHBOARD -->
  <div class="tabpanel grid-gap" id="dashboard">
    <div class="kpi-grid">
      <div class="card kpi-card"><div class="icon">🎯</div><div class="val">{total}</div><div class="lbl">Live Opportunities</div></div>
      <div class="card kpi-card"><div class="icon">🟢</div><div class="val">{t1count}</div><div class="lbl">High Probability</div></div>
      <div class="card kpi-card"><div class="icon">📈</div><div class="val">{avg_score}%</div><div class="lbl">Avg Fit Score</div></div>
      <div class="card kpi-card"><div class="icon">📬</div><div class="val">7–10</div><div class="lbl">Apply This Week</div></div>
    </div>
    <div class="card">
      <h3 class="section-head">Top 10 Priority Applications</h3>
      <div style="overflow-x:auto">
        <table>
          <thead><tr><th>#</th><th>Position</th><th>Company</th><th>Fit Score</th><th>Action</th></tr></thead>
          <tbody>{top10_rows}</tbody>
        </table>
      </div>
    </div>
    <div class="two-col">
      <div class="card">
        <h3 class="section-head">Weekly Job Search Plan</h3>
        <div class="plan-row"><span class="plan-day d-apply">Mon</span><p style="margin:0;font-size:13px;color:#334155;line-height:1.5">Apply to all Tier 1 jobs from this week's update</p></div>
        <div class="plan-row"><span class="plan-day d-apply">Tue</span><p style="margin:0;font-size:13px;color:#334155;line-height:1.5">Tailor resume for top 2–3 companies; submit applications</p></div>
        <div class="plan-row"><span class="plan-day d-network">Wed</span><p style="margin:0;font-size:13px;color:#334155;line-height:1.5">Connect with 5 GTA PM recruiters on LinkedIn (Michael Page, Hays, Randstad)</p></div>
        <div class="plan-row"><span class="plan-day d-apply">Thu</span><p style="margin:0;font-size:13px;color:#334155;line-height:1.5">Apply to Tier 2 jobs; update LinkedIn 'Open to Work' with role targets</p></div>
        <div class="plan-row"><span class="plan-day d-prep">Fri</span><p style="margin:0;font-size:13px;color:#334155;line-height:1.5">Follow up on applications sent Monday; research companies who viewed your profile</p></div>
        <div class="plan-row"><span class="plan-day d-network">Sat</span><p style="margin:0;font-size:13px;color:#334155;line-height:1.5">Attend PMI GTA Chapter event or webinar; connect with 3 alumni</p></div>
        <div class="plan-row"><span class="plan-day d-prep">Sun</span><p style="margin:0;font-size:13px;color:#334155;line-height:1.5">Review this week's results; prepare for any upcoming interviews</p></div>
        <div class="plan-footer"><strong>Target:</strong> 7–10 applications/week in weeks 1–2; 4–6/week thereafter with follow-ups.</div>
      </div>
      <div class="card">
        <h3 class="section-head">Recommended GTA Recruiters</h3>
        <div class="rec-row"><div><p class="name">Hays Engineering &amp; Construction</p><p class="focus">Infrastructure, PM, scheduling</p></div><a href="https://www.hays.ca" target="_blank">Visit →</a></div>
        <div class="rec-row"><div><p class="name">Michael Page Canada</p><p class="focus">Senior PM / Director roles</p></div><a href="https://www.michaelpage.ca" target="_blank">Visit →</a></div>
        <div class="rec-row"><div><p class="name">Randstad Engineering</p><p class="focus">Civil, construction, PM</p></div><a href="https://www.randstad.ca" target="_blank">Visit →</a></div>
        <div class="rec-row"><div><p class="name">Goldbeck Recruiting</p><p class="focus">Construction &amp; real estate PM</p></div><a href="https://www.goldbeck.com" target="_blank">Visit →</a></div>
        <div class="rec-row"><div><p class="name">Cartel Inc.</p><p class="focus">Construction, project controls</p></div><a href="https://www.cartelinc.com" target="_blank">Visit →</a></div>
        <div style="margin-top:14px;padding:10px 14px;background:var(--accentL);border-radius:8px;font-size:12px;color:#78350F;">
          💡 Open with your Eglinton Crosstown LRT experience — it's a strong conversation starter with any GTA recruiter.
        </div>
      </div>
    </div>
    <div class="card">
      <h3 class="section-head">Industries with Strongest GTA PM Demand (2026)</h3>
      <div class="industry-grid">
        <div class="ind-item"><div class="ind-row"><span>Transit &amp; LRT</span><span>95%</span></div><div class="bar"><div class="bar-fill" style="width:95%;background:var(--g1c)"></div></div><p class="ind-note">Eglinton, Finch, Scarborough RT expansion ongoing</p></div>
        <div class="ind-item"><div class="ind-row"><span>Civil Infrastructure</span><span>88%</span></div><div class="bar"><div class="bar-fill" style="width:88%;background:var(--g1c)"></div></div><p class="ind-note">Provincial highway, GO expansion, water/wastewater</p></div>
        <div class="ind-item"><div class="ind-row"><span>Commercial Construction</span><span>80%</span></div><div class="bar"><div class="bar-fill" style="width:80%;background:var(--teal)"></div></div><p class="ind-note">Office-to-residential conversions, mixed-use</p></div>
        <div class="ind-item"><div class="ind-row"><span>Industrial / Logistics</span><span>75%</span></div><div class="bar"><div class="bar-fill" style="width:75%;background:var(--teal)"></div></div><p class="ind-note">Distribution centres, EV manufacturing facilities</p></div>
        <div class="ind-item"><div class="ind-row"><span>Energy / Utilities</span><span>72%</span></div><div class="bar"><div class="bar-fill" style="width:72%;background:var(--accent)"></div></div><p class="ind-note">Grid modernisation, nuclear refurbishment</p></div>
        <div class="ind-item"><div class="ind-row"><span>Healthcare Capital</span><span>68%</span></div><div class="bar"><div class="bar-fill" style="width:68%;background:var(--accent)"></div></div><p class="ind-note">Hospital expansions, long-term care</p></div>
      </div>
    </div>
  </div>

</div>

<script>
document.querySelectorAll(".nav button").forEach(btn => {{
  btn.addEventListener("click", () => {{
    document.querySelectorAll(".nav button").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tabpanel").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(btn.dataset.tab).classList.add("active");
  }});
}});
document.querySelectorAll(".job-card").forEach(card => {{
  const btn = card.querySelector(".toggle-btn");
  if (btn) btn.addEventListener("click", () => {{
    card.classList.toggle("open");
    btn.textContent = card.classList.contains("open") ? "▲ Less" : "▼ Details";
  }});
}});
</script>
</body>
</html>"""


def render_job_card(job: dict, rank: int) -> str:
    sc = job["_score"]
    t = job["_tier"]
    title = job.get("job_title", "Untitled Role")
    company = job.get("employer_name", "Unknown Company")
    location = job.get("job_city", "") + (", " + job.get("job_state", "") if job.get("job_state") else "")
    salary = fmt_salary(job)
    emp_type = job.get("job_employment_type", "")
    apply_url = job.get("job_apply_link", "#")
    company_url = job.get("employer_website", "") or apply_url
    desc = (job.get("job_description") or "")[:800].strip()

    score_cls = "high" if sc >= 75 else "med" if sc >= 60 else "low"
    tier_cls = f"t{t}"
    tier_label = "Tier 1 – High Probability" if t == 1 else "Tier 2 – Medium Probability" if t == 2 else "Tier 3 – Stretch"

    meta_parts = [f"🏢 {company}"]
    if location.strip(" ,"):
        meta_parts.append(f"📍 {location}")
    if salary:
        meta_parts.append(f"💰 {salary}")
    if emp_type:
        meta_parts.append(f"⏱ {emp_type.replace('_', ' ').title()}")

    desc_html = f'<div class="desc-box">{desc}</div>' if desc else ""

    return f"""
<div class="card job-card">
  <div class="job-top">
    <div class="job-info">
      <div class="job-title-row">
        <span class="job-rank">#{rank}</span>
        <span class="job-title">{title}</span>
        <span class="tier-tag {tier_cls}">{tier_label}</span>
      </div>
      <p class="job-meta">{" &nbsp;·&nbsp; ".join(meta_parts)}</p>
    </div>
    <div class="job-right">
      <span class="score {score_cls}">{sc}/100</span>
      <button class="toggle-btn">▼ Details</button>
    </div>
  </div>
  <div class="job-details">
    {desc_html}
    <div class="links-row">
      <a class="btn-apply" href="{apply_url}" target="_blank" rel="noopener noreferrer">Apply Now →</a>
      <a class="btn-company" href="{company_url}" target="_blank" rel="noopener noreferrer">Company Page</a>
    </div>
  </div>
</div>"""


def render_job_list(jobs: list[dict], start_rank: int = 1) -> str:
    if not jobs:
        return '<div class="no-jobs">No jobs found in this tier for this update.</div>'
    return "\n".join(render_job_card(j, i + start_rank) for i, j in enumerate(jobs))


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    print("=== GTA PM Job Search — Auto-Update ===")
    print(f"Fetching jobs from JSearch API...")

    raw_jobs = []
    for q in SEARCH_QUERIES:
        print(f"  Searching: {q}")
        results = fetch_jobs_for_query(q)
        print(f"    → {len(results)} results")
        raw_jobs.extend(results)

    raw_jobs = dedup(raw_jobs)
    print(f"\nTotal unique jobs: {len(raw_jobs)}")

    # Score and sort
    for j in raw_jobs:
        j["_score"] = score_job(j)
        j["_tier"] = tier(j["_score"])

    raw_jobs.sort(key=lambda j: j["_score"], reverse=True)

    t1 = [j for j in raw_jobs if j["_tier"] == 1]
    t2 = [j for j in raw_jobs if j["_tier"] == 2]
    t3 = [j for j in raw_jobs if j["_tier"] == 3]

    total = len(raw_jobs)
    avg_score = round(sum(j["_score"] for j in raw_jobs) / total) if total else 0

    # Top 10 table rows
    top10_rows = ""
    for i, j in enumerate(raw_jobs[:10]):
        sc = j["_score"]
        score_cls = "high" if sc >= 75 else "med" if sc >= 60 else "low"
        apply_url = j.get("job_apply_link", "#")
        top10_rows += f"""
        <tr>
          <td style="font-weight:800;color:var(--accent)">#{i+1}</td>
          <td style="font-weight:600;color:var(--navy)">{j.get('job_title','')}</td>
          <td style="color:var(--muted)">{j.get('employer_name','')}</td>
          <td><span class="score {score_cls}">{sc}/100</span></td>
          <td><a href="{apply_url}" target="_blank" style="color:var(--accent);font-weight:700;font-size:12px;text-decoration:none">Apply →</a></td>
        </tr>"""

    updated_at = datetime.now(timezone.utc).strftime("%A, %B %-d %Y at %H:%M UTC")

    html = HTML_TEMPLATE.format(
        updated_at=updated_at,
        total=total,
        t1count=len(t1),
        t2count=len(t2),
        t3count=len(t3),
        avg_score=avg_score,
        all_jobs_html=render_job_list(raw_jobs),
        t1_jobs_html=render_job_list(t1),
        t2_jobs_html=render_job_list(t2, start_rank=len(t1)+1),
        t3_jobs_html=render_job_list(t3, start_rank=len(t1)+len(t2)+1),
        top10_rows=top10_rows,
    )

    out = Path("index.html")
    out.write_text(html, encoding="utf-8")
    print(f"\n✅ index.html written ({out.stat().st_size // 1024} KB)")
    print(f"   Tier 1: {len(t1)} | Tier 2: {len(t2)} | Tier 3: {len(t3)}")


if __name__ == "__main__":
    main()

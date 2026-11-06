# TrackRight website - by Muneeb Ur Rehman
# home page -> upload CV -> skills, career path, live job suggestions
# run:  python app.py   then open http://127.0.0.1:5000

import html as htmllib
import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, quote_plus
from urllib.request import Request, urlopen

from flask import Flask, render_template, request
from jinja2 import DictLoader

import trackright as tr

BASE = Path(__file__).resolve().parent  # always look next to app.py
JOBS_FILE = str(BASE / "jobs_sample.csv")  # fallback if live jobs fail
DB_FILE = str(BASE / "trackright.db")
ALLOWED = {".pdf", ".docx", ".txt"}

# free job APIs, no key needed. Remotive asks to link back to the job
# page and not to poll too often, so results are cached for 10 minutes.
REMOTIVE_URL = "https://remotive.com/api/remote-jobs?limit=40&search={}"
ARBEITNOW_URL = "https://www.arbeitnow.com/api/job-board-api"
CACHE_SECONDS = 600
_CACHE = {}

# search words sent to the job API for each career direction
SEARCH_TERMS = {
    "AI/ML": ["python", "machine learning"],
    "web dev": ["web developer", "flask"],
    "QA/testing": ["qa", "software tester"],
    "data": ["data analyst", "data entry"],
    "support": ["customer support", "chat support"],
}

# career path shown to the user for each direction
PATHS = {
    "AI/ML": {
        "now": ["AI Intern", "Junior Python Developer", "AI Trainer / LLM Evaluator"],
        "later": ["Junior AI Engineer", "Applied AI / ML Engineer", "RAG / LLM Developer"],
    },
    "web dev": {
        "now": ["Web Developer Intern", "Flask / Python Backend Intern", "MERN Stack Intern"],
        "later": ["Full Stack Developer", "Backend Engineer"],
    },
    "QA/testing": {
        "now": ["QA Intern", "Junior SQA Engineer", "Manual Tester"],
        "later": ["Automation QA Engineer", "SDET"],
    },
    "data": {
        "now": ["Data Entry Specialist", "Data Analyst Intern"],
        "later": ["Junior Data Analyst", "BI / Reporting Analyst"],
    },
    "support": {
        "now": ["Chat Support Agent", "Customer Support Executive"],
        "later": ["Support Team Lead", "QA Analyst (Support)", "CRM Specialist"],
    },
}

# words that appear in normal sentences ("express interest", "excel in")
# so they only count for a job if they are in its title or tags
AMBIGUOUS = {"express", "excel", "communication"}
OPEN_WORDS = ["worldwide", "anywhere", "global", "asia", "pakistan", "apac"]

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB upload limit


# ---------- live jobs ----------

def fetch_json(url):
    hit = _CACHE.get(url)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    try:
        req = Request(url, headers={"User-Agent": "TrackRight/1.0"})
        with urlopen(req, timeout=8) as resp:
            data = json.load(resp)
    except Exception:
        return None
    _CACHE[url] = (time.time(), data)
    return data


def clean_text(raw):
    text = re.sub(r"<[^>]+>", " ", raw or "")
    return re.sub(r"\s+", " ", htmllib.unescape(text)).lower()


def days_since(value):
    try:
        if isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(value, timezone.utc)
        else:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - dt).days)
    except Exception:
        return 0


def safe_url(url):
    url = (url or "").strip()
    return url if url.startswith(("http://", "https://")) else ""


def fetch_live_jobs(terms):
    """Returns (jobs, ok). ok is False if no API answered."""
    jobs, seen, ok = [], set(), False

    for term in terms:
        data = fetch_json(REMOTIVE_URL.format(quote(term)))
        if not data or "jobs" not in data:
            continue
        ok = True
        for j in data["jobs"]:
            url = safe_url(j.get("url"))
            if not url or url in seen:
                continue
            seen.add(url)
            loc = j.get("candidate_required_location") or "Remote"
            jobs.append({
                "title": j.get("title") or "",
                "company": j.get("company_name") or "",
                "location": loc,
                "type": (j.get("job_type") or "").replace("_", " "),
                "days": days_since(j.get("publication_date")),
                "url": url, "source": "Remotive",
                "tags": [j.get("category") or ""],
                "text": clean_text(j.get("description")),
                "open_pk": any(w in loc.lower() for w in OPEN_WORDS),
            })

    data = fetch_json(ARBEITNOW_URL)
    if data and "data" in data:
        ok = True
        for j in data["data"]:
            url = safe_url(j.get("url"))
            if not url or url in seen:
                continue
            seen.add(url)
            jobs.append({
                "title": j.get("title") or "",
                "company": j.get("company_name") or "",
                "location": "Remote (check region)" if j.get("remote") else (j.get("location") or ""),
                "type": ", ".join(j.get("job_types") or []),
                "days": days_since(j.get("created_at")),
                "url": url, "source": "Arbeitnow",
                "tags": j.get("tags") or [],
                "text": clean_text(j.get("description")),
                "open_pk": False,
            })
    return jobs, ok


def score_live(found, jobs, limit=12):
    """Same idea as the terminal matcher: skills the job mentions vs skills you have."""
    scored = []
    for j in jobs:
        head = (j["title"] + " " + " ".join(j["tags"])).lower()
        both = head + " " + j["text"]
        required = []
        for skill in tr.SKILLS:
            where = head if skill in AMBIGUOUS else both
            if tr.has_skill(where, skill):
                required.append(skill)
        matched = [s for s in required if s in found]
        missing = [s for s in required if s not in found]
        if not matched or (j["source"] == "Arbeitnow" and len(matched) < 2):
            continue
        scored.append({
            "title": j["title"], "company": j["company"], "location": j["location"],
            "type": j["type"], "posted_days_ago": j["days"],
            "matched": matched, "missing": missing,
            "percent": round(len(matched) / len(required) * 100),
            "url": j["url"], "source": j["source"], "open_pk": j["open_pk"],
        })
    scored.sort(key=lambda r: (not r["open_pk"], -r["percent"],
                               -len(r["matched"]), r["posted_days_ago"]))
    return scored[:limit]


def search_links(role):
    q = quote_plus(role)
    return {
        "role": role,
        "linkedin": "https://www.linkedin.com/jobs/search/?keywords=" + q + "&location=Pakistan",
        "indeed": "https://pk.indeed.com/jobs?q=" + q + "&l=Lahore",
        "rozee": "https://www.rozee.pk/job/jsearch/q/" + quote(role),
    }


# ---------- pages ----------

@app.get("/")
def home():
    return render_template("home.html")


@app.route("/analyze", methods=["GET", "POST"])
def analyze():
    if request.method == "GET":
        return render_template("analyze.html", error=None)

    file = request.files.get("cv")
    if not file or not file.filename:
        return render_template("analyze.html", error="Please choose a CV file first."), 400
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED:
        return render_template("analyze.html", error="Only PDF, DOCX or TXT files are supported."), 400

    # save the upload to a temp file so tr.read_cv can open it by path
    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    try:
        file.save(tmp_path)
        text = tr.read_cv(tmp_path)
    except tr.TrackRightError as e:
        return render_template("analyze.html", error=str(e)), 400
    finally:
        os.remove(tmp_path)

    found = tr.find_skills(text)
    if not found:
        return render_template(
            "analyze.html",
            error="No known skills found in this CV. Check the file has real text "
                  "(not a scanned image) and lists your skills."), 400

    best, counts, _ = tr.build_roadmap(found)
    strength = [{"name": name, "count": counts[name], "total": len(tr.BUCKETS[name]),
                 "pct": round(counts[name] / len(tr.BUCKETS[name]) * 100)}
                for name in tr.BUCKETS]
    strength.sort(key=lambda s: -s["count"])
    others = [s["name"] for s in strength if s["name"] != best and s["count"] > 0][:2]
    learn = [s for s in tr.NEXT_SKILLS[best] if not tr.has_skill(" ".join(found), s)]
    path = PATHS[best]

    live, ok = [], False
    jobs, ok = fetch_live_jobs(SEARCH_TERMS[best])
    if ok:
        live = score_live(found, jobs)

    sample = []
    if not live and Path(JOBS_FILE).exists():
        sample_jobs, _warn = tr.read_jobs(JOBS_FILE)
        sample = tr.match_jobs(text, sample_jobs)[:8]

    tr.save_to_db(DB_FILE, file.filename, found, live or sample)

    return render_template(
        "results.html", filename=file.filename, found=found, best=best,
        strength=strength, others=others, learn=learn, path=path,
        live=live, live_ok=ok, sample=sample,
        links=[search_links(r) for r in path["now"][:2]])


@app.errorhandler(413)
def too_big(_e):
    return render_template("analyze.html", error="File is too large (max 5 MB)."), 413


# ---------- templates ----------

TEMPLATES = {
"base.html": """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{% block title %}TrackRight - CV to career path{% endblock %}</title>
<style>
  :root { --bg:#f6f7fb; --card:#fff; --text:#1c2230; --muted:#667085; --line:#e4e7ee;
          --accent:#3b5bdb; --accent2:#7048e8; --good:#2f9e44; --goodbg:#e6f6ea;
          --bad:#c92a2a; --badbg:#fdeaea; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#10131a; --card:#1a1e29; --text:#e8eaf0; --muted:#98a2b3; --line:#2b3140;
            --accent:#748ffc; --accent2:#9775fa; --good:#69db7c; --goodbg:#1a3322;
            --bad:#ff8787; --badbg:#3a1d1d; }
  }
  * { box-sizing:border-box; }
  body { margin:0; font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
         background:var(--bg); color:var(--text); line-height:1.5; }
  a { color:var(--accent); }
  .nav { display:flex; justify-content:space-between; align-items:center;
         max-width:1000px; margin:0 auto; padding:16px; }
  .nav nav { display:flex; gap:18px; align-items:center; }
  .nav nav a { text-decoration:none; color:var(--muted); }
  .brand { font-weight:800; font-size:22px; text-decoration:none; color:var(--text); }
  .brand span { color:var(--accent); }
  main { max-width:1000px; margin:0 auto; padding:0 16px 56px; }
  footer { text-align:center; color:var(--muted); font-size:13px; padding:24px; }
  .btn { display:inline-block; padding:12px 24px; border-radius:10px; border:0; cursor:pointer;
         background:linear-gradient(135deg,var(--accent),var(--accent2)); color:#fff !important;
         text-decoration:none; font-size:16px; font-weight:600; }
  .btn.small { padding:8px 16px; font-size:14px; }
  .btn.ghost { background:transparent; color:var(--accent) !important; border:1px solid var(--line); }
  .btn.mini { padding:6px 12px; font-size:13px; }
  .hero { text-align:center; padding:56px 0 40px; }
  .hero h1 { font-size:44px; line-height:1.15; margin:0 0 14px; }
  .hero h1 em { font-style:normal; background:linear-gradient(135deg,var(--accent),var(--accent2));
                -webkit-background-clip:text; background-clip:text; color:transparent; }
  .hero p { color:var(--muted); font-size:18px; max-width:600px; margin:0 auto 26px; }
  .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(230px,1fr)); gap:16px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:14px;
          padding:20px; margin-bottom:16px; }
  .grid .card { margin:0; }
  .step { width:34px; height:34px; border-radius:50%; background:var(--accent); color:#fff;
          display:flex; align-items:center; justify-content:center; font-weight:700; margin-bottom:10px; }
  h2 { margin:32px 0 12px; font-size:22px; }
  h3 { margin:0 0 6px; }
  .muted { color:var(--muted); }
  .chip { display:inline-block; padding:3px 10px; margin:3px 4px 3px 0; border-radius:999px;
          font-size:13px; border:1px solid var(--line); }
  .chip.ok { background:var(--goodbg); color:var(--good); border-color:transparent; }
  .chip.no { background:var(--badbg); color:var(--bad); border-color:transparent; }
  .drop { position:relative; border:2px dashed var(--line); border-radius:14px;
          padding:46px 20px; text-align:center; background:var(--card); }
  .drop:hover, .drop.over { border-color:var(--accent); }
  .drop input { position:absolute; inset:0; width:100%; height:100%; opacity:0; cursor:pointer; }
  .error { background:var(--badbg); color:var(--bad); padding:12px 14px; border-radius:10px; margin-bottom:16px; }
  .bar { height:8px; background:var(--line); border-radius:999px; overflow:hidden; }
  .bar > div { height:100%; background:linear-gradient(90deg,var(--accent),var(--accent2)); }
  .row { display:flex; justify-content:space-between; font-size:14px; margin:12px 0 4px; }
  .pct { float:right; font-weight:800; font-size:22px; color:var(--accent); }
  .label { font-size:13px; color:var(--muted); margin-top:8px; }
  .role { padding:8px 12px; margin:6px 0; border-radius:10px; background:var(--bg); border:1px solid var(--line); }
  .hero-result { background:linear-gradient(135deg,var(--accent),var(--accent2)); color:#fff;
                 border-radius:16px; padding:26px; margin:8px 0 16px; }
  .hero-result h1 { margin:4px 0; font-size:34px; }
  .hero-result .chip { color:#fff; border-color:rgba(255,255,255,.4); }
  .note { color:var(--muted); font-size:13px; }
</style></head>
<body>
<header class="nav">
  <a class="brand" href="/">Track<span>Right</span></a>
  <nav><a href="/">Home</a><a class="btn small" href="/analyze">Analyze my CV</a></nav>
</header>
<main>{% block content %}{% endblock %}</main>
<footer>TrackRight &middot; built by Muneeb ur Rehman</footer>
</body></html>""",

"home.html": """{% extends "base.html" %}
{% block content %}
<section class="hero">
  <h1>Turn your CV into a <em>career path</em></h1>
  <p>Upload your CV. TrackRight finds your skills, shows where you fit best,
     and suggests real jobs you can apply to today.</p>
  <a class="btn" href="/analyze">Analyze my CV</a>
</section>

<h2>How it works</h2>
<div class="grid">
  <div class="card"><div class="step">1</div><h3>Upload your CV</h3>
    <p class="muted">PDF, DOCX or TXT. Nothing is kept except your skill results.</p></div>
  <div class="card"><div class="step">2</div><h3>We read your skills</h3>
    <p class="muted">Python, Flask, QA, support and more are detected and grouped by area.</p></div>
  <div class="card"><div class="step">3</div><h3>Get your path and jobs</h3>
    <p class="muted">See your best-fit direction, what to learn next, and live job matches.</p></div>
</div>

<h2>What you get</h2>
<div class="grid">
  <div class="card"><h3>Skill strength</h3><p class="muted">How strong you are in AI/ML, web, QA, data and support.</p></div>
  <div class="card"><h3>Career roadmap</h3><p class="muted">Roles to apply for now, skills to learn, roles to grow into.</p></div>
  <div class="card"><h3>Live job matches</h3><p class="muted">Jobs from the internet ranked by how well your skills fit.</p></div>
  <div class="card"><h3>Local search links</h3><p class="muted">One click to LinkedIn, Indeed and Rozee searches for your target roles.</p></div>
</div>
<p style="text-align:center;margin-top:36px"><a class="btn" href="/analyze">Try it with your CV</a></p>
{% endblock %}""",

"analyze.html": """{% extends "base.html" %}
{% block title %}Analyze CV - TrackRight{% endblock %}
{% block content %}
<section class="hero" style="padding-bottom:20px">
  <h1>Analyze your <em>CV</em></h1>
  <p>Drop your CV below to see your skills, career path and job matches.</p>
</section>
{% if error %}<div class="error">{{ error }}</div>{% endif %}
<form id="f" method="post" action="/analyze" enctype="multipart/form-data">
  <div class="drop" id="drop">
    <input type="file" name="cv" id="cv" accept=".pdf,.docx,.txt" required>
    <div style="font-size:36px">&#128196;</div>
    <strong id="name">Click or drag your CV here</strong>
    <p class="note">PDF, DOCX or TXT, max 5 MB. Scanned image-only PDFs will not work.</p>
  </div>
  <p style="text-align:center"><button class="btn" id="go" type="submit">Analyze my CV</button></p>
</form>
<script>
  var cv = document.getElementById("cv"), drop = document.getElementById("drop");
  cv.addEventListener("change", function () {
    if (cv.files.length) document.getElementById("name").textContent = cv.files[0].name;
  });
  ["dragenter","dragover"].forEach(function (e) {
    drop.addEventListener(e, function () { drop.classList.add("over"); });
  });
  ["dragleave","drop"].forEach(function (e) {
    drop.addEventListener(e, function () { drop.classList.remove("over"); });
  });
  document.getElementById("f").addEventListener("submit", function () {
    var b = document.getElementById("go"); b.textContent = "Analyzing..."; b.disabled = true;
  });
</script>
{% endblock %}""",

"results.html": """{% extends "base.html" %}
{% block title %}Your results - TrackRight{% endblock %}
{% block content %}
<div class="hero-result">
  <div>Best fit for {{ filename }}</div>
  <h1>{{ best }}</h1>
  <div>{{ found|length }} skills found
    {% if others %}&middot; also close to: {{ others|join(", ") }}{% endif %}</div>
</div>

<h2>Your skills</h2>
<div class="card">
  {% for s in found %}<span class="chip ok">{{ s }}</span>{% endfor %}
</div>

<h2>Skill strength by area</h2>
<div class="card">
  {% for s in strength %}
  <div class="row"><span>{{ s.name }}</span><span class="muted">{{ s.count }} of {{ s.total }} skills</span></div>
  <div class="bar"><div style="width: {{ s.pct }}%"></div></div>
  {% endfor %}
</div>

<h2>Your career path</h2>
<div class="grid">
  <div class="card"><h3>1. Apply now</h3><p class="note">Roles that match your current skills</p>
    {% for r in path.now %}<div class="role">{{ r }}</div>{% endfor %}</div>
  <div class="card"><h3>2. Learn next</h3><p class="note">Skills that unlock better roles</p>
    {% for s in learn %}<div class="role">{{ s }}</div>
    {% else %}<div class="role">You have these covered</div>{% endfor %}</div>
  <div class="card"><h3>3. Grow into</h3><p class="note">Where this direction leads</p>
    {% for r in path.later %}<div class="role">{{ r }}</div>{% endfor %}</div>
</div>

<h2>Job suggestions</h2>
{% if live %}
  <p class="note">Live remote jobs from the internet, ranked by how many of the skills they mention you have.
     Jobs open to Pakistan or worldwide come first.</p>
  {% for r in live %}
  <div class="card">
    <span class="pct">{{ r.percent }}%</span>
    <h3>{{ r.title }}</h3>
    <div class="muted">{{ r.company }} &middot; {{ r.location }}{% if r.type %} &middot; {{ r.type }}{% endif %}
      &middot; {{ r.posted_days_ago }} days ago
      {% if r.open_pk %}<span class="chip ok">Open to Pakistan</span>{% endif %}</div>
    <div class="bar" style="margin:10px 0"><div style="width: {{ r.percent }}%"></div></div>
    <div class="label">You have</div>
    {% for s in r.matched %}<span class="chip ok">{{ s }}</span>{% endfor %}
    {% if r.missing %}<div class="label">To add</div>
    {% for s in r.missing[:6] %}<span class="chip no">{{ s }}</span>{% endfor %}{% endif %}
    <p style="margin:12px 0 0"><a class="btn mini" href="{{ r.url }}" target="_blank" rel="noopener noreferrer">View and apply</a>
      <span class="note">via {{ r.source }}</span></p>
  </div>
  {% endfor %}
{% else %}
  <div class="card">
    {% if live_ok %}
      <p>No live jobs matched your skills right now. Use the search links below.</p>
    {% else %}
      <p>Could not reach the job sites (check your internet). Showing sample jobs instead.</p>
    {% endif %}
  </div>
  {% for r in sample %}
  <div class="card">
    <span class="pct">{{ r.percent }}%</span>
    <h3>{{ r.title }}</h3>
    <div class="muted">{{ r.company }} &middot; {{ r.location }} &middot; {{ r.type }} <span class="chip">sample</span></div>
    <div class="bar" style="margin:10px 0"><div style="width: {{ r.percent }}%"></div></div>
    {% for s in r.matched %}<span class="chip ok">{{ s }}</span>{% endfor %}
    {% for s in r.missing %}<span class="chip no">{{ s }}</span>{% endfor %}
  </div>
  {% endfor %}
{% endif %}

<h2>Search local jobs</h2>
<div class="card">
  <p class="note">Most Pakistani jobs are not on free APIs, so search them directly:</p>
  {% for l in links %}
  <p><strong>{{ l.role }}</strong><br>
    <a class="btn ghost mini" href="{{ l.linkedin }}" target="_blank" rel="noopener noreferrer">LinkedIn</a>
    <a class="btn ghost mini" href="{{ l.indeed }}" target="_blank" rel="noopener noreferrer">Indeed PK</a>
    <a class="btn ghost mini" href="{{ l.rozee }}" target="_blank" rel="noopener noreferrer">Rozee</a></p>
  {% endfor %}
</div>

<p style="margin-top:28px"><a class="btn" href="/analyze">Analyze another CV</a></p>
{% endblock %}""",
}

app.jinja_env.loader = DictLoader(TEMPLATES)

if __name__ == "__main__":
    app.run(debug=True)

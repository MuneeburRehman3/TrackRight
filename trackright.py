# TrackRight - by Muneeb Ur Rehman
# reads a cv (.txt, .pdf or .docx), finds the skills in it,
# and ranks jobs from a csv by how well they fit

import argparse
import csv
import re
import sqlite3
from contextlib import closing
from datetime import datetime
from functools import lru_cache
from pathlib import Path

DEFAULT_CV = "cv_sample.txt"
DEFAULT_JOBS = "jobs_sample.csv"
DEFAULT_DB = "trackright.db"
DEFAULT_REPORT = "matches_report.txt"

REQUIRED_JOB_COLUMNS = ["title", "company", "location", "type",
                        "skills_required", "posted_days_ago"]

# skills the parser looks for, add more here when you learn something new
SKILLS = [
    "python", "flask", "sqlalchemy", "sql", "postgresql", "mysql", "sqlite",
    "langchain", "rag", "llm evaluation", "embeddings", "gemini",
    "prompt engineering", "computer vision", "pandas", "numpy",
    "javascript", "react", "html", "css", "git", "github",
    "mern", "node", "express", "mongodb",
    "qa", "manual testing", "automation testing", "selenium",
    "data entry", "data analysis", "excel",
    "customer support", "chat support", "communication",
    "machine learning", "deep learning", "nlp", "api",
]

# other ways people write the same skill (canonical name -> aliases)
ALIASES = {
    "python": ["python3"],
    "javascript": ["js", "ecmascript"],
    "node": ["node.js", "nodejs"],
    "express": ["express.js", "expressjs"],
    "react": ["react.js", "reactjs"],
    "postgresql": ["postgres"],
    "sqlite": ["sqlite3"],
    "mongodb": ["mongo"],
    "machine learning": ["ml"],
    "nlp": ["natural language processing"],
    "rag": ["retrieval augmented generation", "retrieval-augmented generation"],
    "llm evaluation": ["llm evals", "llm eval"],
    "embeddings": ["embedding"],
    "qa": ["quality assurance", "sqa", "software quality assurance"],
    "api": ["apis", "rest api", "rest apis"],
    "excel": ["ms excel", "microsoft excel"],
    "automation testing": ["test automation", "automated testing"],
    "manual testing": ["manual qa"],
    "customer support": ["customer service"],
    "chat support": ["live chat support"],
    "html": ["html5"],
    "css": ["css3"],
}
ALIAS_TO_CANON = {a: c for c, aliases in ALIASES.items() for a in aliases}

# which bucket each skill belongs to, for the roadmap part
BUCKETS = {
    "AI/ML": ["python", "langchain", "rag", "llm evaluation", "embeddings",
              "gemini", "prompt engineering", "computer vision", "pandas",
              "numpy", "machine learning", "deep learning", "nlp"],
    "web dev": ["flask", "sqlalchemy", "javascript", "react", "html", "css",
                "git", "github", "mern", "node", "express", "mongodb", "api"],
    "QA/testing": ["qa", "manual testing", "automation testing", "selenium"],
    "data": ["sql", "postgresql", "mysql", "sqlite", "data entry",
             "data analysis", "excel", "pandas", "numpy"],
    "support": ["customer support", "chat support", "communication"],
}

# next skills to suggest for each direction
NEXT_SKILLS = {
    "AI/ML": ["agentic ai / tool calling", "vector databases", "fastapi"],
    "web dev": ["react", "fastapi", "docker"],
    "QA/testing": ["selenium", "api testing", "automation testing"],
    "data": ["pandas", "power bi", "excel"],
    "support": ["crm tools", "salesforce basics", "ticketing systems"],
}

ROLE_TARGETS = {
    "AI/ML": "ai intern, python developer and generative ai roles, "
             "then junior ai engineer roles once you have one more shipped project.",
    "web dev": "junior web developer and flask/python backend roles, "
               "then full stack roles once react is solid.",
    "QA/testing": "qa intern and sqa roles, then automation qa once selenium is solid.",
    "data": "data analyst intern and data entry roles, then junior data analyst roles.",
    "support": "customer support and chat support roles, "
               "then team lead or qa roles in support teams.",
}


class TrackRightError(Exception):
    """Problem with an input file that the user can fix."""


# ---------- skill matching ----------

@lru_cache(maxsize=None)
def _pattern(term):
    # whole-word match: "rag" must not match "storage", "git" not "digital".
    # lookarounds (not \b) so terms like "node.js" still work.
    return re.compile(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])")


def canonical(skill):
    skill = skill.strip().lower()
    return ALIAS_TO_CANON.get(skill, skill)


def has_skill(text, skill):
    """True if the skill (or one of its aliases) appears as a whole word."""
    skill = canonical(skill)
    terms = [skill] + ALIASES.get(skill, [])
    return any(_pattern(t).search(text) for t in terms)


def find_skills(text):
    return [skill for skill in SKILLS if has_skill(text, skill)]


# ---------- reading input ----------

def read_cv(path):
    p = Path(path)
    if not p.exists():
        raise TrackRightError("cv file not found: " + str(path))

    suffix = p.suffix.lower()
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            raise TrackRightError("PDF support needs pypdf: pip install pypdf")
        reader = PdfReader(str(p))
        text = " ".join((page.extract_text() or "") for page in reader.pages)
    elif suffix == ".docx":
        try:
            import docx
        except ImportError:
            raise TrackRightError("DOCX support needs python-docx: pip install python-docx")
        document = docx.Document(str(p))
        parts = [para.text for para in document.paragraphs]
        for table in document.tables:
            for row in table.rows:
                parts.extend(cell.text for cell in row.cells)
        text = " ".join(parts)
    else:
        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()

    # collapse line breaks/extra spaces so multi-word skills match across lines
    text = re.sub(r"\s+", " ", text).lower().strip()
    if not text:
        raise TrackRightError("cv file is empty or has no readable text "
                              "(scanned PDFs need OCR): " + str(path))
    return text


def read_jobs(path):
    """Returns (jobs, warnings). Bad rows are skipped with a warning."""
    p = Path(path)
    if not p.exists():
        raise TrackRightError("jobs file not found: " + str(path))

    jobs = []
    warnings = []
    with open(p, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        columns = [c.strip() for c in (reader.fieldnames or [])]
        missing_cols = [c for c in REQUIRED_JOB_COLUMNS if c not in columns]
        if missing_cols:
            raise TrackRightError("jobs csv is missing columns: " + ", ".join(missing_cols))

        for line_no, row in enumerate(reader, start=2):
            row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
            try:
                days = int(row["posted_days_ago"])
            except ValueError:
                warnings.append("line " + str(line_no) + ": bad posted_days_ago, row skipped")
                continue

            # split on commas, normalise, drop empties and duplicates (keep order)
            required = []
            for s in row["skills_required"].split(","):
                s = canonical(s)
                if s and s not in required:
                    required.append(s)
            if not row["title"] or not required:
                warnings.append("line " + str(line_no) + ": no title or no skills, row skipped")
                continue

            row["skills_required"] = required
            row["posted_days_ago"] = days
            jobs.append(row)
    return jobs, warnings


# ---------- matching and roadmap ----------

def match_jobs(cv_text, jobs):
    # checks each required skill against the cv text itself, so skills
    # that are not in SKILLS (like docker) can still match
    results = []
    for job in jobs:
        matched = []
        missing = []
        for skill in job["skills_required"]:
            if has_skill(cv_text, skill):
                matched.append(skill)
            else:
                missing.append(skill)
        total = len(job["skills_required"])
        percent = round(len(matched) / total * 100) if total > 0 else 0
        results.append({
            "title": job["title"],
            "company": job["company"],
            "location": job["location"],
            "type": job["type"],
            "posted_days_ago": job["posted_days_ago"],
            "matched": matched,
            "missing": missing,
            "percent": percent,
        })
    # best match first; on a tie the newer posting wins
    results.sort(key=lambda r: (-r["percent"], r["posted_days_ago"], r["title"]))
    return results


def build_roadmap(found):
    counts = {name: sum(1 for s in skills if s in found)
              for name, skills in BUCKETS.items()}
    top = max(counts.values())
    if top == 0:
        return None, counts, ["no known skills found in the cv, "
                              "check the file or add skills to SKILLS"]

    tied = [name for name, c in counts.items() if c == top]
    best = tied[0]
    # don't suggest things the cv already has
    next_skills = [s for s in NEXT_SKILLS[best] if not has_skill(" ".join(found), s)]

    lines = ["your strongest direction: " + best]
    if len(tied) > 1:
        lines.append("tied with: " + ", ".join(tied[1:])
                     + " (some skills like python/pandas count in more than one area)")
    lines.append("skills found in that area: " + str(top))
    lines.append("next skills to learn: " + (", ".join(next_skills) if next_skills else "you have these covered"))
    lines.append("target next: " + ROLE_TARGETS[best])
    return best, counts, lines


# ---------- output ----------

def format_results(results):
    lines = []
    for rank, r in enumerate(results, start=1):
        lines.append(str(rank) + ". " + r["title"] + " - " + r["company"]
                     + " (" + r["location"] + ", " + r["type"] + ")"
                     + " - " + str(r["percent"]) + "% match")
        lines.append("   matched: " + (", ".join(r["matched"]) or "none"))
        lines.append("   missing: " + (", ".join(r["missing"]) or "none"))
        lines.append("   posted " + str(r["posted_days_ago"]) + " days ago")
    return lines


def save_to_db(db_path, cv_file, found, results):
    """Each run is stored with a timestamp, so history is kept."""
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:  # commits on success, rolls back on error
            cur = conn.cursor()
            cur.execute("CREATE TABLE IF NOT EXISTS runs ("
                        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                        "created_at TEXT, cv_file TEXT)")
            cur.execute("CREATE TABLE IF NOT EXISTS cv_skills ("
                        "run_id INTEGER, skill TEXT)")
            cur.execute("CREATE TABLE IF NOT EXISTS matches ("
                        "run_id INTEGER, title TEXT, company TEXT, location TEXT, "
                        "type TEXT, posted_days_ago INTEGER, match_percent INTEGER, "
                        "matched_skills TEXT, missing_skills TEXT)")

            cur.execute("INSERT INTO runs (created_at, cv_file) VALUES (?, ?)",
                        (datetime.now().isoformat(timespec="seconds"), str(cv_file)))
            run_id = cur.lastrowid

            cur.executemany("INSERT INTO cv_skills VALUES (?, ?)",
                            [(run_id, s) for s in found])
            cur.executemany(
                "INSERT INTO matches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(run_id, r["title"], r["company"], r["location"], r["type"],
                  r["posted_days_ago"], r["percent"],
                  ", ".join(r["matched"]), ", ".join(r["missing"]))
                 for r in results])
    return run_id


def write_report(path, found, results, roadmap_lines, counts):
    lines = ["TrackRight - job matches", "========================", "",
             "skills found in cv (" + str(len(found)) + "): " + ", ".join(found), "",
             "ranked jobs:", ""]
    for line in format_results(results):
        lines.append(line)
        if line.startswith("   posted"):
            lines.append("")
    lines.append("roadmap:")
    lines.extend("- " + line for line in roadmap_lines)
    lines.append("")
    lines.append("skill counts by area: " + str(counts))
    lines.append("")
    lines.append("note: jobs in the csv are samples only, not live listings.")
    Path(path).write_text("\n".join(lines), encoding="utf-8")


# ---------- main ----------

def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="TrackRight - cv to job matcher")
    parser.add_argument("--cv", default=DEFAULT_CV, help="cv file (.txt, .pdf, .docx)")
    parser.add_argument("--jobs", default=DEFAULT_JOBS, help="jobs csv file")
    parser.add_argument("--db", default=DEFAULT_DB, help="sqlite database file")
    parser.add_argument("--report", default=DEFAULT_REPORT, help="report output file")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    print("TrackRight - cv to job matcher")
    print("==============================\n")

    try:
        text = read_cv(args.cv)
        jobs, warnings = read_jobs(args.jobs)
    except TrackRightError as e:
        print("error:", e)
        return 1

    for w in warnings:
        print("warning:", w)
    if not jobs:
        print("error: no usable jobs found in", args.jobs)
        return 1

    found = find_skills(text)
    print("skills found in your cv (" + str(len(found)) + "):")
    print(", ".join(found) or "none")
    print("\njobs checked:", len(jobs), "\n")

    results = match_jobs(text, jobs)
    print("ranked matches:\n")
    print("\n".join(format_results(results)))
    print("")

    _, counts, roadmap_lines = build_roadmap(found)
    print("roadmap:")
    for line in roadmap_lines:
        print("- " + line)
    print("\nskill counts by area:", counts, "\n")

    save_to_db(args.db, args.cv, found, results)
    write_report(args.report, found, results, roadmap_lines, counts)
    print("saved to " + args.db + " and " + args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

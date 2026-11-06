# TrackRight

Built at the GDGoC hackathon, Top 10 at HalShnas BNU Hackathon 2025; this is a
clean rebuild of the same tool — the original code was lost.

## What it is

TrackRight takes a CV as a plain text file, finds the skills in it, and ranks
jobs by how well they fit that skillset. It also suggests a short career
roadmap based on the strongest skill area in the CV.

## The issue it solved

Finding the right job meant reading hundreds of job posts one by one and
guessing which ones actually matched. TrackRight does the matching in seconds:
it pulls the skills out of the CV, checks them against each job's required
skills, and ranks the jobs by match percent, with the missing skills listed
for each one so you know what to learn next.

## How it works

- `trackright.py` — the whole tool, one file, Python standard library only
  (sqlite3, csv, sys). No installs needed.
- `cv_sample.txt` — a sample CV in plain text. Replace it with your own CV
  saved as text to run it on yourself.
- `jobs_sample.csv` — 12 sample junior/intern roles with the skills each one
  asks for. These are samples only, not live listings, and nothing here is
  scraped from any job site.
- Matching is simple and rule-based: match percent = required skills found in
  the CV divided by total required skills. No machine learning, no fake
  claims — just counting.
- The roadmap groups the found skills into AI/ML, web dev, QA/testing, data
  and support, picks the strongest area, and suggests 2–3 skills to learn
  next and which roles to target.

## How to run it

```bash
python3 trackright.py
```

That prints the ranked matches and the roadmap, saves everything to
`trackright.db` (tables: `cv_skills`, `jobs`, `matches`) and writes
`matches_report.txt` with the same results.

## What it found on the sample CV

23 skills found. Top matches: AI Intern at Databiqs (100%), Python Developer
Intern at 10Pearls (100%), Generative AI Intern at Arbisoft (100%).
Strongest direction: AI/ML (10 skills), next to learn: agentic AI /
tool calling, vector databases, FastAPI.

## Notes

- This is a clean rebuild written in Nov 2026. The original 2025 hackathon
  code was lost, so this version was written from the same idea and the same
  CV description, not recovered from the original files.
- The sample CV is built from the author's real CV. The sample jobs are
  illustrative only.

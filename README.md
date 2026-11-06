# TrackRight

Built at the GDGoC hackathon, Top 10 at HalShnas BNU Hackathon 2025. 

## Screenshots

![Home page](screenshots/home.png)
![Upload page](screenshots/upload.png)
![Skills and career path](screenshots/results.png)
![Job suggestions](screenshots/jobs.png)

## What it is

TrackRight takes a CV (PDF, DOCX or TXT), finds the skills in it, suggests a career path, and ranks jobs by how well they fit that skill set.

## The issue it solved

Finding the right job meant reading hundreds of job posts one by one and guessing which ones actually matched. TrackRight does the matching in seconds. It pulls the skills out of the CV, checks them against each job's required skills, and ranks jobs by match percent. The missing skills are listed for each job, so you know what to learn next.

## Features

- Upload a CV in the browser (PDF, DOCX or TXT)
- Skill detection with whole-word matching and aliases (js, postgres, node.js)
- Skill strength across AI/ML, web dev, QA/testing, data and support
- Career path: roles to apply for now, skills to learn next, roles to grow into
- Live remote jobs from the internet, ranked by skill match
- Search links for LinkedIn, Indeed PK and Rozee
- Every run is saved to a local SQLite database

## How it works

- `trackright.py` is the core engine. It reads the CV, finds skills, matches jobs and builds the roadmap. It also runs on its own in the terminal.
- `app.py` is the Flask website: home page, upload page and results page. It also fetches live jobs from the free Remotive and Arbeitnow APIs.
- `jobs_sample.csv` has sample junior and intern roles. It is the fallback when live jobs can't be loaded. These are samples only, and nothing is scraped from any job site.
- `test_trackright.py` has the pytest tests.
- Matching is simple and rule-based: match percent = required skills found in the CV divided by total required skills. No machine learning, no fake claims, just counting.

## How to run it

```bash
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:5000 and upload a CV.

Terminal version:

```bash
python trackright.py --cv your_cv.txt
```

Tests:

```bash
pytest
```

## Notes

- Live jobs are mostly remote. Pakistani local jobs are covered by the search links.
- Scanned image-only PDFs are not supported (no OCR).

## Author

Muneeb ur Rehman, BS Computer Science, Superior University, Lahore

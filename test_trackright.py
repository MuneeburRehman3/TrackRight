import sqlite3

import pytest

import trackright as tr


def test_no_substring_false_positives():
    text = "great storage, leverage, digital work, excellent, rapid growth"
    assert not tr.has_skill(text, "rag")
    assert not tr.has_skill(text, "git")
    assert not tr.has_skill(text, "excel")
    assert not tr.has_skill(text, "api")


def test_mysql_does_not_count_as_sql():
    assert not tr.has_skill("i know mysql", "sql")
    assert tr.has_skill("i know mysql and sql", "sql")


def test_aliases_match():
    text = "built apis with node.js, postgres and js"
    found = tr.find_skills(text)
    assert {"node", "postgresql", "api", "javascript"} <= set(found)


def test_job_skill_outside_skills_list_can_match():
    jobs = [{"title": "Dev", "company": "X", "location": "Lahore", "type": "intern",
             "posted_days_ago": 1, "skills_required": ["docker", "python"]}]
    result = tr.match_jobs("i use docker and python", jobs)[0]
    assert result["percent"] == 100


def test_tie_goes_to_newer_posting():
    base = {"company": "X", "location": "L", "type": "intern", "skills_required": ["python"]}
    jobs = [dict(base, title="Old", posted_days_ago=10),
            dict(base, title="New", posted_days_ago=2)]
    results = tr.match_jobs("python", jobs)
    assert [r["title"] for r in results] == ["New", "Old"]


def test_read_jobs_skips_bad_rows_and_warns(tmp_path):
    f = tmp_path / "jobs.csv"
    f.write_text("title,company,location,type,skills_required,posted_days_ago\n"
                 "A,X,L,intern,\"python, sql\",3\n"
                 "B,X,L,intern,python,abc\n", encoding="utf-8")
    jobs, warnings = tr.read_jobs(f)
    assert len(jobs) == 1 and len(warnings) == 1


def test_read_jobs_missing_column_raises(tmp_path):
    f = tmp_path / "jobs.csv"
    f.write_text("title,company\nA,X\n", encoding="utf-8")
    with pytest.raises(tr.TrackRightError):
        tr.read_jobs(f)


def test_read_cv_missing_file_raises(tmp_path):
    with pytest.raises(tr.TrackRightError):
        tr.read_cv(tmp_path / "nope.txt")


def test_roadmap_reports_ties_and_empty():
    best, counts, lines = tr.build_roadmap(["pandas"])
    assert any("tied with" in line for line in lines)
    best, counts, lines = tr.build_roadmap([])
    assert best is None


def test_roadmap_skips_skills_already_known():
    _, _, lines = tr.build_roadmap(["qa", "selenium", "manual testing"])
    next_line = [l for l in lines if l.startswith("next skills")][0]
    assert "selenium" not in next_line


def test_db_keeps_history(tmp_path):
    db = tmp_path / "t.db"
    results = [{"title": "A", "company": "X", "location": "L", "type": "intern",
                "posted_days_ago": 1, "percent": 50, "matched": ["python"], "missing": ["sql"]}]
    tr.save_to_db(db, "cv.txt", ["python"], results)
    tr.save_to_db(db, "cv.txt", ["python"], results)
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 2


def test_main_end_to_end(tmp_path):
    cv = tmp_path / "cv.txt"
    cv.write_text("Python developer, Flask, SQLite, Git.", encoding="utf-8")
    jobs = tmp_path / "jobs.csv"
    jobs.write_text("title,company,location,type,skills_required,posted_days_ago\n"
                    "Dev,X,Lahore,intern,\"python, flask\",1\n", encoding="utf-8")
    code = tr.main(["--cv", str(cv), "--jobs", str(jobs),
                    "--db", str(tmp_path / "t.db"), "--report", str(tmp_path / "r.txt")])
    assert code == 0
    assert (tmp_path / "r.txt").exists()

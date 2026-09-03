import copy
import json
import sqlite3
import subprocess
import time
import uuid
from pathlib import Path


def uid():
    return str(uuid.uuid4())


def now():
    return time.time()


class Store:
    def __init__(self, root: Path):
        self.root = root
        self.on_project_saved = None
        root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(root / "projects.sqlite3")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
        self.db.commit()
        for job in self.jobs():
            if job["status"] in ("running", "queued", "paused"):
                job.update(status="interrupted", error="App riavviata. Le slide già salvate sono conservate.")
                self.save_job(job)

    def _save(self, table, item):
        item["updated_at"] = now()
        self.db.execute(f"INSERT OR REPLACE INTO {table} VALUES (?,?)",
                        (item["id"], json.dumps(item, ensure_ascii=False)))
        self.db.commit()
        if table == "projects" and self.on_project_saved:
            try:
                self.on_project_saved(item)
            except (OSError, subprocess.SubprocessError):
                import logging
                logging.exception("Sincronizzazione Slidev non riuscita")
        return copy.deepcopy(item)

    def project(self, pid):
        row = self.db.execute("SELECT body FROM projects WHERE id=?", (pid,)).fetchone()
        if not row:
            raise KeyError("Progetto non trovato")
        return json.loads(row[0])

    def projects(self):
        return sorted((json.loads(row[0]) for row in self.db.execute("SELECT body FROM projects")),
                      key=lambda p: p["updated_at"], reverse=True)

    def save_project(self, project):
        return self._save("projects", project)

    def create(self, values):
        return self.save_project(dict(id=uid(), created_at=now(), revision=1,
                                      slides=[], sources=[], **values))

    def jobs(self):
        return sorted((json.loads(row[0]) for row in self.db.execute("SELECT body FROM jobs")),
                      key=lambda j: j["updated_at"], reverse=True)

    def job(self, jid):
        row = self.db.execute("SELECT body FROM jobs WHERE id=?", (jid,)).fetchone()
        if not row:
            raise KeyError("Job non trovato")
        return json.loads(row[0])

    def save_job(self, job):
        return self._save("jobs", job)

    def event(self, jid, message, **updates):
        job = self.job(jid)
        job.update(updates)
        job["events"] = (job.get("events", []) + [{"at": now(), "message": message}])[-120:]
        return self.save_job(job)

    def asset_path(self, pid, name):
        self.project(pid)
        if not name or Path(name).name != name or "/" in name or "\\" in name:
            raise ValueError("Nome file non valido")
        root = (self.root / "assets" / pid).resolve()
        target = (root / name).resolve()
        if not target.is_relative_to(root):
            raise ValueError("Percorso non valido")
        root.mkdir(parents=True, exist_ok=True)
        return target

import copy
import json
import sqlite3
import subprocess
import time
import uuid
import shutil
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
        self.db.execute("CREATE TABLE IF NOT EXISTS app_state (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
        self.db.commit()
        for job in self.jobs():
            if job["status"] in ("running", "queued", "paused"):
                job.update(status="interrupted", error="App riavviata. Le slide già salvate sono conservate.")
                self.save_job(job)

    def _save(self, table, item, notify=True):
        item["updated_at"] = now()
        self.db.execute(f"INSERT OR REPLACE INTO {table} VALUES (?,?)",
                        (item["id"], json.dumps(item, ensure_ascii=False)))
        self.db.commit()
        if table == "projects" and notify and self.on_project_saved:
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

    def save_project(self, project, notify=True):
        return self._save("projects", project, notify=notify)

    def create(self, values):
        return self.save_project(dict(id=uid(), created_at=now(), revision=1,
                                      slides=[], sources=[], **values))

    def fork_project(self, pid, settings):
        """Independent version with its own assets; deleting either version is safe."""
        original = self.project(pid)
        root_id = original.get("version_root", pid)
        version = max((p.get("version_number", 1) for p in self.projects()
                       if p.get("version_root", p["id"]) == root_id), default=1)+1
        clone = copy.deepcopy(original)
        base_title = settings["title"]
        if base_title == original["title"]:
            base_title = original.get("version_title", base_title)
        clone.update(settings)
        clone.update(id=uid(), created_at=now(), revision=1, version_root=root_id,
                     version_number=version, parent_project_id=pid, version_title=base_title,
                     title=base_title[:125]+f" (v{version})")
        assets_root = (self.root / "assets").resolve()
        source, target = (assets_root / pid).resolve(), (assets_root / clone["id"]).resolve()
        if not source.is_relative_to(assets_root) or not target.is_relative_to(assets_root):
            raise ValueError("Percorso risorse non valido")
        if source.exists():
            if any(p.is_symlink() for p in source.rglob("*")):
                raise ValueError("Le risorse contengono collegamenti simbolici: impossibile duplicarle in sicurezza")
            shutil.copytree(source, target)
        clone.pop("web_research", None)
        return self.save_project(clone)

    def state(self, key, default):
        row = self.db.execute("SELECT body FROM app_state WHERE id=?", (key,)).fetchone()
        return json.loads(row[0]) if row else copy.deepcopy(default)

    def save_state(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO app_state VALUES (?,?)",
                        (key, json.dumps(value, ensure_ascii=False)))
        self.db.commit()
        return copy.deepcopy(value)

    def delete_project(self, pid):
        self.project(pid)
        job_ids = [job["id"] for job in self.jobs() if job.get("project_id") == pid]
        self.db.execute("DELETE FROM projects WHERE id=?", (pid,))
        self.db.executemany("DELETE FROM jobs WHERE id=?", ((jid,) for jid in job_ids))
        self.db.commit()

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

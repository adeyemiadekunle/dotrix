"""Background task runner.

A "job" is a PM-agent invocation that runs independently of any interactive
`pmagent chat` session, on the SAME project state — same `.pmagent/` files,
same SQLite checkpoint DB — coordinated through small JSON records rather
than by holding anything in this process's memory. This is what makes
concurrency work:

  - every job (and every chat session) gets its OWN thread_id, so LangGraph
    checkpoints each independently even though they all share one SQLite file
  - file writes go through LockingFilesystemBackend (see backend.py), so two
    jobs — or a job and a chat session — writing the same file serialize
    instead of racing
  - a job that crashes is marked status="failed" with the error, instead
    of sitting at "running" forever
  - a job that hits an Action Mode approval doesn't block waiting for a
    human to be watching a particular terminal: it records
    status="awaiting_approval" and exits; `pmagent jobs-approve <id>` resumes
    it later, from any terminal
"""
from __future__ import annotations

import json
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .config import ProjectConfig

JOBS_DIRNAME = "jobs"


def _jobs_dir(config: ProjectConfig) -> Path:
    d = Path(config.pmagent_dir) / JOBS_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _job_path(config: ProjectConfig, job_id: str) -> Path:
    return _jobs_dir(config) / f"{job_id}.json"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def write_job(config: ProjectConfig, job_id: str, **fields) -> dict:
    path = _job_path(config, job_id)
    data = json.loads(path.read_text()) if path.exists() else {}
    data.update(fields)
    data["updated_at"] = _now()
    path.write_text(json.dumps(data, indent=2))
    return data


def get_job(config: ProjectConfig, job_id: str) -> dict:
    path = _job_path(config, job_id)
    if not path.exists():
        raise FileNotFoundError(f"No such job: {job_id}")
    return json.loads(path.read_text())


def list_jobs(config: ProjectConfig) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(_jobs_dir(config).glob("*.json"))]


def start_job(config: ProjectConfig, instruction: str, background: bool) -> dict:
    job_id = uuid.uuid4().hex[:8]
    thread_id = f"job-{job_id}"
    log_path = _jobs_dir(config) / f"{job_id}.log"
    write_job(
        config, job_id,
        id=job_id, instruction=instruction, thread_id=thread_id,
        status="running", started_at=_now(), log_path=str(log_path),
    )

    args = [
        sys.executable, "-m", "pmagent_engine.jobs_worker",
        "--project", config.root_dir, "--job-id", job_id,
        "--thread-id", thread_id, "--message", instruction,
    ]

    if background:
        with open(log_path, "w") as log:
            subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        return get_job(config, job_id)
    subprocess.run(args)
    return get_job(config, job_id)


def resume_job(config: ProjectConfig, job_id: str, decision: str, background: bool,
               reject_message: str | None = None) -> dict:
    job = get_job(config, job_id)
    if job["status"] != "awaiting_approval":
        raise ValueError(f"Job {job_id} is '{job['status']}', not awaiting approval.")

    args = [
        sys.executable, "-m", "pmagent_engine.jobs_worker",
        "--project", config.root_dir, "--job-id", job_id,
        "--thread-id", job["thread_id"], "--resume", decision,
    ]
    if reject_message:
        args += ["--reject-message", reject_message]
    log_path = Path(job["log_path"])

    if background:
        with open(log_path, "a") as log:
            subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        return get_job(config, job_id)
    subprocess.run(args)
    return get_job(config, job_id)

from __future__ import annotations

import json
import threading
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from digital_resident.config import settings


def jobs_dir() -> Path:
    d = settings()["root"] / "data" / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def job_path(job_id: str) -> Path:
    return jobs_dir() / f"{job_id}.json"


def write_job(job_id: str, payload: dict[str, Any]) -> None:
    path = job_path(job_id)
    tmp = path.with_suffix(".tmp")
    data = dict(payload)
    data["updated_at"] = _now()
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def read_job(job_id: str) -> dict[str, Any] | None:
    path = job_path(job_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def latest_active_job() -> dict[str, Any] | None:
    jobs = []
    for p in jobs_dir().glob("*.json"):
        try:
            j = json.loads(p.read_text(encoding="utf-8"))
            jobs.append(j)
        except Exception:
            continue
    running = [j for j in jobs if j.get("status") == "running"]
    if running:
        running.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
        return running[0]
    done = [j for j in jobs if j.get("status") in {"done", "error"}]
    if not done:
        return None
    done.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
    return done[0]


def start_job(
    *,
    kind: str,
    label: str,
    target: Callable[[], dict[str, Any]],
) -> str:
    job_id = uuid.uuid4().hex[:12]
    write_job(
        job_id,
        {
            "id": job_id,
            "kind": kind,
            "label": label,
            "status": "running",
            "created_at": _now(),
            "error": None,
            "result_path": None,
        },
    )

    def _worker() -> None:
        meta = read_job(job_id) or {}
        created = meta.get("created_at") or _now()
        try:
            result = target()
            out = jobs_dir() / f"{job_id}_result.json"
            out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            write_job(
                job_id,
                {
                    "id": job_id,
                    "kind": kind,
                    "label": label,
                    "status": "done",
                    "created_at": created,
                    "error": None,
                    "result_path": str(out),
                },
            )
        except Exception as e:
            write_job(
                job_id,
                {
                    "id": job_id,
                    "kind": kind,
                    "label": label,
                    "status": "error",
                    "created_at": created,
                    "error": f"{e}\n{traceback.format_exc()}",
                    "result_path": None,
                },
            )

    t = threading.Thread(target=_worker, name=f"cdss-job-{job_id}", daemon=True)
    t.start()
    return job_id


def load_job_result(job: dict[str, Any]) -> dict[str, Any] | None:
    path = job.get("result_path")
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))

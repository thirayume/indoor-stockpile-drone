"""In-process background jobs for long-running work (reconstructions).

A reconstruction takes minutes to hours, far beyond an HTTP request budget,
so the API submits work here and clients poll job state.

Scope note: state lives in this process and the executor defaults to a
single worker because reconstructions are CPU-bound and OpenSfM writes into
a shared project folder — run exactly one API process (uvicorn's default).
If the API ever needs replicas or restart-safe jobs, replace this with a
persistent queue (e.g. Redis + workers); the JobManager surface is the seam.
"""

import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from core.logging import get_logger

logger = get_logger(__name__)


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in (JobStatus.SUCCEEDED, JobStatus.FAILED)


@dataclass
class Job:
    id: str
    kind: str
    params: dict[str, Any]
    status: JobStatus = JobStatus.QUEUED
    progress: str | None = None  # human-readable current step
    error: str | None = None
    result: dict[str, Any] | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None


# A job function receives its Job (to publish progress) and returns the result.
JobFn = Callable[[Job], dict[str, Any]]


class JobManager:
    def __init__(self, max_workers: int = 1) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="job")
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def submit(self, kind: str, params: dict[str, Any], fn: JobFn) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, params=params)
        with self._lock:
            self._jobs[job.id] = job
        self._executor.submit(self._run, job, fn)
        logger.info("Job %s queued (%s, params=%s)", job.id, kind, params)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    def _run(self, job: Job, fn: JobFn) -> None:
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(UTC)
        try:
            job.result = fn(job)
            job.status = JobStatus.SUCCEEDED
            logger.info("Job %s succeeded", job.id)
        except Exception as exc:  # noqa: BLE001 - job boundary: report, don't crash the worker
            job.status = JobStatus.FAILED
            job.error = str(exc)
            logger.exception("Job %s failed", job.id)
        finally:
            job.finished_at = datetime.now(UTC)


# Application-wide manager; single reconstruction at a time by design.
job_manager = JobManager(max_workers=1)

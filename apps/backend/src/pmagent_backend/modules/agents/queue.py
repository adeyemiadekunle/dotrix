"""The agent-run queue: the API enqueues runs, the worker (`python -m pmagent_backend.worker`)
executes them. Built on arq (Redis): jobs survive API restarts, a worker that dies has its
job retried, and a job can be aborted (Stop)."""
from __future__ import annotations

import uuid
from typing import Any

from arq.jobs import Job
from uuid_utils.compat import uuid7

from pmagent_backend.core.jobs import QUEUE_NAME

KEY_TTL_SECONDS = 24 * 3600


class RunQueue:
    def __init__(self, redis: Any, queue_name: str = QUEUE_NAME) -> None:
        self.redis, self.queue_name = redis, queue_name

    def _key(self, run_id: uuid.UUID, what: str) -> str:
        return f"{self.queue_name}:run:{run_id}:{what}"

    async def enqueue(self, run_id: uuid.UUID, payload: dict[str, Any]) -> None:
        """Queue one step of a run (its start, or its resumption after decisions)."""
        job_id = f"{run_id}:{uuid7().hex}"
        await self.redis.set(self._key(run_id, "job"), job_id, ex=KEY_TTL_SECONDS)
        await self.redis.enqueue_job(
            "run_agent", str(run_id), payload, _job_id=job_id, _queue_name=self.queue_name
        )

    async def stop(self, run_id: uuid.UUID, reason: str, timeout: float = 10) -> bool:
        """Abort the run's current job, queued or working. The worker reads `reason` when it
        records the stop. False if there's no job to stop."""
        job_id = await self.redis.get(self._key(run_id, "job"))
        if not job_id:
            return False
        await self.redis.set(self._key(run_id, "stop"), reason, ex=KEY_TTL_SECONDS)
        job = Job(job_id.decode() if isinstance(job_id, bytes) else job_id, self.redis, _queue_name=self.queue_name)
        try:
            return await job.abort(timeout=timeout)
        except TimeoutError:
            return False

    async def stop_reason(self, run_id: uuid.UUID) -> str | None:
        reason = await self.redis.get(self._key(run_id, "stop"))
        return reason.decode() if isinstance(reason, bytes) else reason

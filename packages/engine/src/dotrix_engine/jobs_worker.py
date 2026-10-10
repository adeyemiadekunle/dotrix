"""Worker for a single background job: `python -m dotrix_engine.jobs_worker ...`.

Spawned as a subprocess by jobs.start_job / jobs.resume_job so it runs
detached from any interactive session. Never prompts for input. If the PM
agent needs an Action Mode approval, this records `awaiting_approval`
(with the pending actions as JSON) and exits rather than blocking on a
terminal nobody's watching.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from . import approvals
from .agent import build_agent
from .config import ProjectConfig
from .jobs import get_job, write_job


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--thread-id", required=True)
    parser.add_argument("--message")
    parser.add_argument("--resume", choices=["approve", "reject"])
    parser.add_argument("--reject-message")
    args = parser.parse_args()

    config = ProjectConfig.load(args.project)
    checkpoint_path = Path(config.dotrix_dir) / "checkpoints.sqlite"
    cfg = {"configurable": {"thread_id": args.thread_id}}

    try:
        with SqliteSaver.from_conn_string(str(checkpoint_path)) as checkpointer:
            agent = build_agent(config, checkpointer=checkpointer)

            if args.resume:
                pending = get_job(config, args.job_id).get("pending_actions") or []
                cmd = approvals.resume_command(pending, args.resume, args.reject_message)
                write_job(config, args.job_id, status="running", pending_actions=None)
                result = agent.invoke(cmd, cfg)
            else:
                result = agent.invoke({"messages": [{"role": "user", "content": args.message}]}, cfg)

            if approvals.has_pending(result):
                actions = approvals.pending_actions(result)
                write_job(config, args.job_id, status="awaiting_approval", pending_actions=actions)
                print(f"[job {args.job_id}] awaiting approval:")
                for a in actions:
                    print(approvals.format_action(a), end="\n\n")
            else:
                final = result["messages"][-1].content
                write_job(config, args.job_id, status="done", result=final)
                print(final)
    except Exception as e:  # otherwise a crash leaves the job "running" forever
        write_job(config, args.job_id, status="failed", error=f"{type(e).__name__}: {e}")
        raise


if __name__ == "__main__":
    main()

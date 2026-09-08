"""Process-safe run admission and durable idempotency on one shared local volume.

All methods are synchronous: async routes must call them in a threadpool. Acquire
before saving user messages or making provider requests; complete after durable
response storage, and always close tickets in a finally block. A running ticket
renews its fenced lease in a daemon thread until closed or completed.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Callable
from uuid import UUID, uuid4

from . import config


class RunRejected(Exception):
    """Admission rejection with an HTTP-safe machine-readable reason."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 409,
        *,
        run_id: str | None = None,
        status: str | None = None,
        retry_after: int | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.run_id = run_id
        self.status = status
        self.retry_after = retry_after


class LeaseLost(RuntimeError):
    """An expired/finalized lease must never publish a late result."""


@dataclass(frozen=True)
class RunLimits:
    max_active: int = 8
    max_user_active: int = 2
    rate_requests: int = 20
    rate_window: float = 60
    lease_seconds: float = 120
    max_models: int = 5

    def __post_init__(self):
        for name in ("max_active", "max_user_active", "rate_requests", "max_models"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        for name in ("rate_window", "lease_seconds"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")

    @classmethod
    def from_env(cls):
        return cls(
            max_active=int(os.getenv("RUN_MAX_ACTIVE", "8")),
            max_user_active=int(os.getenv("RUN_MAX_USER_ACTIVE", "2")),
            rate_requests=int(os.getenv("RUN_RATE_REQUESTS", "20")),
            rate_window=float(os.getenv("RUN_RATE_WINDOW_SECONDS", "60")),
            lease_seconds=float(os.getenv("RUN_LEASE_SECONDS", "120")),
            max_models=config.MAX_COUNCIL_MODELS,
        )


class RunControl:
    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        limits: RunLimits | None = None,
        clock: Callable[[], float] = time.time,
        heartbeat: bool = True,
    ):
        self.db_path = Path(
            db_path or os.getenv("RUN_CONTROL_DB") or Path(config.DATA_DIR).parent / "run_control.sqlite3"
        )
        self.limits = limits or RunLimits.from_env()
        self.clock = clock
        self.heartbeat = heartbeat
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    user TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started REAL NOT NULL,
                    lease_expires REAL NOT NULL,
                    result TEXT,
                    usage TEXT,
                    UNIQUE(user, request_id)
                );
                CREATE INDEX IF NOT EXISTS runs_active ON runs(status, lease_expires);
                CREATE INDEX IF NOT EXISTS runs_user_started ON runs(user, started);
                CREATE INDEX IF NOT EXISTS runs_conversation ON runs(conversation_id, status);
            """)

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA secure_delete=ON")
        try:
            yield connection
        finally:
            connection.close()

    def acquire(
        self, *, user: str, conversation_id: str, payload: dict[str, Any], request_id: str | None = None
    ) -> RunTicket:
        """Admit atomically, replay terminal results, or reject before paid work."""
        if not isinstance(user, str) or not user or not isinstance(conversation_id, str) or not conversation_id:
            raise RunRejected("invalid_identity", "User and conversation ID are required", 422)
        try:
            request_id = str(UUID(request_id)) if request_id is not None else str(uuid4())
        except (ValueError, TypeError, AttributeError) as error:
            raise RunRejected("invalid_request_id", "request_id must be a UUID", 422) from error
        models = payload.get("models")
        if models is not None and (
            not isinstance(models, list)
            or not 1 <= len(models) <= self.limits.max_models
            or any(not isinstance(model, str) or not model for model in models)
            or len(set(models)) != len(models)
        ):
            raise RunRejected("invalid_models", "Models must be nonempty, unique and within the configured limit", 422)
        digest = hashlib.sha256(
            json.dumps(
                {"conversation_id": conversation_id, "payload": payload},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode()
        ).hexdigest()
        now = self.clock()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            # Keep the idempotency record after expiry: retrying it must not pay twice.
            connection.execute("UPDATE runs SET status='aborted' WHERE status='running' AND lease_expires<=?", (now,))
            previous = connection.execute(
                "SELECT * FROM runs WHERE user=? AND request_id=?", (user, request_id)
            ).fetchone()
            if previous:
                connection.commit()
                if previous["digest"] != digest:
                    raise RunRejected(
                        "idempotency_conflict",
                        "request_id was used for a different request",
                        run_id=previous["run_id"],
                        status=previous["status"],
                    )
                if previous["status"] in {"completed", "partial"}:
                    return RunTicket(self, previous, replayed=True)
                raise RunRejected(
                    "duplicate_run",
                    "Run already exists; failed/aborted runs require a new request_id",
                    run_id=previous["run_id"],
                    status=previous["status"],
                )
            busy = connection.execute(
                "SELECT run_id FROM runs WHERE conversation_id=? AND status='running'", (conversation_id,)
            ).fetchone()
            if busy:
                raise RunRejected(
                    "conversation_busy",
                    "This conversation already has an active run",
                    run_id=busy["run_id"],
                    status="running",
                )
            total = connection.execute("SELECT COUNT(*) FROM runs WHERE status='running'").fetchone()[0]
            if total >= self.limits.max_active:
                raise RunRejected("global_limit", "Active run limit reached", 429, retry_after=1)
            user_active = connection.execute(
                "SELECT COUNT(*) FROM runs WHERE user=? AND status='running'", (user,)
            ).fetchone()[0]
            if user_active >= self.limits.max_user_active:
                raise RunRejected("user_limit", "Your active run limit is reached", 429, retry_after=1)
            recent = connection.execute(
                "SELECT COUNT(*), MIN(started) FROM runs WHERE user=? AND started>?",
                (user, now - self.limits.rate_window),
            ).fetchone()
            if recent[0] >= self.limits.rate_requests:
                retry_after = max(1, math.ceil(recent[1] + self.limits.rate_window - now))
                raise RunRejected("rate_limit", "Your run rate limit is reached", 429, retry_after=retry_after)
            run_id = str(uuid4())
            connection.execute(
                "INSERT INTO runs(run_id,user,conversation_id,request_id,digest,status,started,lease_expires) VALUES(?,?,?,?,?,'running',?,?)",
                (run_id, user, conversation_id, request_id, digest, now, now + self.limits.lease_seconds),
            )
            row = connection.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            connection.commit()
        return RunTicket(self, row)


class RunTicket:
    """One lease token; terminal operations are fenced against expired owners."""

    def __init__(self, control: RunControl, row: sqlite3.Row, *, replayed: bool = False):
        self.control = control
        self.run_id = row["run_id"]
        self.request_id = row["request_id"]
        self.status = row["status"]
        self.replayed = replayed
        self.result = json.loads(row["result"]) if row["result"] is not None else None
        self.usage = json.loads(row["usage"]) if row["usage"] is not None else None
        self._stop = threading.Event()
        self._lost = threading.Event()
        self._thread = None
        if not replayed and control.heartbeat:
            self._thread = threading.Thread(target=self._heartbeat, name=f"run-lease-{self.run_id}", daemon=True)
            self._thread.start()

    def _heartbeat(self):
        while not self._stop.wait(self.control.limits.lease_seconds / 3):
            try:
                self.renew()
            except (LeaseLost, sqlite3.Error):
                self._lost.set()
                return

    def ensure_active(self):
        if self._lost.is_set():
            raise LeaseLost("Run lease renewal failed")
        with self.control._connection() as connection:
            row = connection.execute("SELECT status, lease_expires FROM runs WHERE run_id=?", (self.run_id,)).fetchone()
        if not row or row["status"] != "running" or row["lease_expires"] <= self.control.clock():
            raise LeaseLost("Run lease expired or was finalized")

    def renew(self):
        now = self.control.clock()
        with self.control._connection() as connection:
            updated = connection.execute(
                "UPDATE runs SET lease_expires=? WHERE run_id=? AND status='running' AND lease_expires>?",
                (now + self.control.limits.lease_seconds, self.run_id, now),
            )
        if not updated.rowcount:
            raise LeaseLost("Run lease expired or was finalized")

    def complete(self, result: dict[str, Any], *, usage: Any = None):
        self._finish("completed", result, usage)

    def fail(self, *, status: str = "failed", result: dict[str, Any] | None = None, usage: Any = None):
        if status not in {"partial", "failed", "aborted"}:
            raise ValueError("Invalid failure status")
        self._finish(status, result, usage)

    def _finish(self, status: str, result: Any, usage: Any):
        result_json = json.dumps(result, ensure_ascii=False, allow_nan=False) if result is not None else None
        usage_json = json.dumps(usage, ensure_ascii=False, allow_nan=False) if usage is not None else None
        with self.control._connection() as connection:
            updated = connection.execute(
                "UPDATE runs SET status=?,result=?,usage=? WHERE run_id=? AND status='running' AND lease_expires>?",
                (status, result_json, usage_json, self.run_id, self.control.clock()),
            )
        if not updated.rowcount:
            self._stop.set()
            raise LeaseLost("Run lease expired or was finalized; result was not published")
        self.status, self.result, self.usage = status, result, usage
        self._stop_heartbeat()

    def _stop_heartbeat(self):
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=11)

    def close(self):
        """Release unfinished work, including cancellation; safe to call repeatedly."""
        try:
            if self.status == "running" and not self.replayed:
                self.fail(status="aborted")
        except LeaseLost:
            self.status = "aborted"
        finally:
            self._stop_heartbeat()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


def forget_conversation_runs(conversation_id):
    """Erase cached answers and fence active work when its conversation is deleted.

    Retain only the idempotency tombstone and non-content usage accounting so
    an old request ID can never silently pay for the same operation again.
    """
    path = Path(os.getenv("RUN_CONTROL_DB") or Path(config.DATA_DIR).parent / "run_control.sqlite3")
    if not path.exists():
        return
    control = RunControl(path)
    with control._connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "UPDATE runs SET result=NULL, status=CASE WHEN status='running' THEN 'aborted' ELSE status END WHERE conversation_id=?",
            (conversation_id,),
        )
        connection.commit()

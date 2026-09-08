"""Admission, durable deduplication, lease fencing and multiprocess regression tests."""
import multiprocessing
from uuid import uuid4

import pytest

from backend.run_control import RunControl, RunLimits, RunRejected, LeaseLost


@pytest.fixture
def control(tmp_path):
    return RunControl(tmp_path / "runs.sqlite3", heartbeat=False)


def acquire(control, user="alice", conversation="one", request_id=None, **kwargs):
    return control.acquire(user=user, conversation_id=conversation,
                           request_id=request_id, payload={"message": "hello", "models": ["m"]}, **kwargs)


def test_duplicate_completed_replays_after_new_control_instance(control):
    request_id = str(uuid4())
    first = acquire(control, request_id=request_id)
    first.complete({"stage1": [{"response": "answer"}]}, usage=[{"model": "m", "total_tokens": 7}])
    second = acquire(RunControl(control.db_path, heartbeat=False), request_id=request_id)
    assert second.replayed
    assert second.run_id == first.run_id
    assert second.result == {"stage1": [{"response": "answer"}]}
    assert second.usage == [{"model": "m", "total_tokens": 7}]


def test_running_duplicate_and_changed_payload_do_not_execute(control):
    request_id = str(uuid4())
    with acquire(control, request_id=request_id) as first:
        with pytest.raises(RunRejected) as error:
            acquire(control, request_id=request_id)
        assert error.value.status_code == 409
        assert error.value.run_id == first.run_id
        with pytest.raises(RunRejected, match="different"):
            control.acquire(user="alice", conversation_id="one", request_id=request_id, payload={"message": "different"})


@pytest.mark.parametrize("status", ["failed", "aborted"])
def test_failed_or_aborted_id_never_silently_reexecutes(control, status):
    request_id = str(uuid4())
    first = acquire(control, request_id=request_id)
    first.fail(status=status)
    with pytest.raises(RunRejected) as error:
        acquire(control, request_id=request_id)
    assert error.value.status == status
    assert error.value.run_id == first.run_id
    with acquire(control) as fresh:
        assert fresh.run_id != first.run_id


def test_partial_result_replays_without_second_run(control):
    request_id = str(uuid4())
    first = acquire(control, request_id=request_id)
    first.fail(status="partial", result={"stage1": ["partial"]})
    replay = acquire(control, request_id=request_id)
    assert replay.replayed and replay.status == "partial"
    assert replay.result == {"stage1": ["partial"]}


def test_same_conversation_is_exclusive_across_users(control):
    with acquire(control):
        with pytest.raises(RunRejected) as error:
            acquire(control, user="bob")
        assert error.value.code == "conversation_busy"


def test_user_and_global_limits(tmp_path):
    control = RunControl(tmp_path / "runs.sqlite3", limits=RunLimits(max_active=2, max_user_active=1), heartbeat=False)
    with acquire(control):
        with pytest.raises(RunRejected) as error:
            acquire(control, conversation="two")
        assert error.value.code == "user_limit"
        with acquire(control, user="bob", conversation="two"):
            with pytest.raises(RunRejected) as error:
                acquire(control, user="charlie", conversation="three")
            assert error.value.code == "global_limit"
            assert error.value.status_code == 429


def test_rate_window_and_replay_does_not_consume_quota(tmp_path):
    now = [100.0]
    control = RunControl(tmp_path / "runs.sqlite3", limits=RunLimits(rate_requests=1, rate_window=60), clock=lambda: now[0], heartbeat=False)
    request_id = str(uuid4())
    acquire(control, request_id=request_id).complete({})
    assert acquire(control, request_id=request_id).replayed
    with pytest.raises(RunRejected) as error:
        acquire(control)
    assert error.value.code == "rate_limit" and error.value.retry_after == 60
    now[0] += 60
    with acquire(control):
        pass


def test_expired_lease_releases_capacity_but_fences_late_completion(tmp_path):
    now = [100.0]
    control = RunControl(tmp_path / "runs.sqlite3", limits=RunLimits(lease_seconds=10), clock=lambda: now[0], heartbeat=False)
    old = acquire(control)
    now[0] += 11
    with acquire(control):
        with pytest.raises(LeaseLost):
            old.complete({"late": True})
        with pytest.raises(LeaseLost):
            old.renew()
    with pytest.raises(RunRejected) as error:
        acquire(control, request_id=old.request_id)
    assert error.value.status == "aborted"


def test_renew_extends_lease_and_close_frees_slot(tmp_path):
    now = [100.0]
    control = RunControl(tmp_path / "runs.sqlite3", limits=RunLimits(lease_seconds=10), clock=lambda: now[0], heartbeat=False)
    with acquire(control) as ticket:
        now[0] += 8
        ticket.renew()
        now[0] += 8
        ticket.ensure_active()
        with pytest.raises(RunRejected):
            acquire(control)
    with acquire(control):
        pass


@pytest.mark.parametrize("models", [["m", "m"], [str(i) for i in range(6)], []])
def test_service_defends_model_count_and_uniqueness(control, models):
    with pytest.raises(RunRejected) as error:
        control.acquire(user="alice", conversation_id="one", payload={"models": models})
    assert error.value.status_code == 422


def test_uuid_validation_and_identity_scoping(control):
    with pytest.raises(RunRejected):
        acquire(control, request_id="invalid")
    request_id = str(uuid4())
    acquire(control, request_id=request_id).complete({})
    with acquire(control, user="bob", request_id=request_id) as bob:
        assert not bob.replayed


def _process_acquire(path, gate, release, results, user, limit, heartbeat=False):
    try:
        control = RunControl(path, limits=RunLimits(max_active=limit, max_user_active=1, lease_seconds=2), heartbeat=heartbeat)
        gate.wait(10)
        with acquire(control, user=user, conversation=user) as ticket:
            results.put(("accepted", ticket.run_id))
            release.wait(15)
    except RunRejected as error:
        results.put(("rejected", error.status_code))
    except BaseException as error:
        results.put(("error", repr(error)))


def test_multiprocess_admission_never_exceeds_global_limit(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    gate, release, results = ctx.Event(), ctx.Event(), ctx.Queue()
    path = str(tmp_path / "runs.sqlite3")
    processes = [ctx.Process(target=_process_acquire, args=(path, gate, release, results, f"u{i}", 2)) for i in range(6)]
    try:
        for process in processes:
            process.start()
        gate.set()
        outcomes = [results.get(timeout=15) for _ in processes]
        assert sum(row[0] == "accepted" for row in outcomes) == 2, outcomes
        assert sum(row == ("rejected", 429) for row in outcomes) == 4, outcomes
    finally:
        release.set()
        for process in processes:
            process.join(10)
            if process.is_alive():
                process.kill()
                process.join()


def test_process_death_lease_recovery_without_replaying_paid_request(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    gate, release, results = ctx.Event(), ctx.Event(), ctx.Queue()
    path = str(tmp_path / "runs.sqlite3")
    child = ctx.Process(target=_process_acquire, args=(path, gate, release, results, "alice", 1, True))
    child.start()
    gate.set()
    try:
        assert results.get(timeout=15)[0] == "accepted"
        child.kill()
        child.join(10)
        # A future clock represents lease timeout, avoiding a slow sleep.
        import time
        control = RunControl(path, clock=lambda: time.time() + 10, heartbeat=False)
        with acquire(control, conversation="alice"):
            pass
    finally:
        if child.is_alive():
            child.kill()
            child.join()


def test_heartbeat_keeps_long_run_active_and_thread_stops(tmp_path):
    import time

    control = RunControl(tmp_path / "runs.sqlite3", limits=RunLimits(lease_seconds=0.3))
    with acquire(control) as ticket:
        time.sleep(0.8)
        ticket.ensure_active()
        with pytest.raises(RunRejected):
            acquire(control)
        assert ticket._thread.is_alive()
    assert not ticket._thread.is_alive()


@pytest.mark.parametrize("name,value", [("max_active", 0), ("max_user_active", -1), ("rate_requests", 0), ("lease_seconds", 0), ("rate_window", float("inf"))])
def test_invalid_limits_fail_closed(name, value):
    with pytest.raises(ValueError):
        RunLimits(**{name: value})


def test_run_control_env_and_model_limit(tmp_path, monkeypatch):
    from backend import config

    monkeypatch.setenv("RUN_CONTROL_DB", str(tmp_path / "configured.sqlite3"))
    monkeypatch.setenv("RUN_MAX_ACTIVE", "3")
    monkeypatch.setattr(config, "MAX_COUNCIL_MODELS", 1)
    control = RunControl(heartbeat=False)
    assert control.db_path == tmp_path / "configured.sqlite3"
    assert control.limits.max_active == 3
    with pytest.raises(RunRejected):
        control.acquire(user="alice", conversation_id="one", payload={"models": ["one", "two"]})

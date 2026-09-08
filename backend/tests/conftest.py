"""Keep durable run admission records isolated for each test."""

import pytest


@pytest.fixture(autouse=True)
def isolate_run_control(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_CONTROL_DB", str(tmp_path / "run-control.sqlite3"))

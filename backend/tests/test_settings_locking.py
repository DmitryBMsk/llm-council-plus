from contextlib import contextmanager
from backend import runtime_settings, storage


def test_settings_mutation_reuses_portable_file_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_settings, 'SETTINGS_FILE', tmp_path/'settings.json')
    calls=[]
    @contextmanager
    def lock(stream, exclusive=True):
        calls.append(exclusive)
        yield
    monkeypatch.setattr(storage, 'file_lock', lock)
    runtime_settings.mutate_runtime_settings({'council_temperature':.6},actor='admin',action='patch')
    assert calls == [True]

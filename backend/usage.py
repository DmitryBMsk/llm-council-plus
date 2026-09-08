"""Request-local observed provider usage, separate from estimated TOON savings.

Missing usage and prices remain unknown. Totals sum reported fields only;
coverage counts expose incomplete accounting (including failed/retried calls).
"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import math
from numbers import Real

_entries = ContextVar('provider_usage_entries', default=None)
_stage = ContextVar('provider_usage_stage', default=None)
_FIELDS = {'prompt_tokens': 'prompt_tokens', 'completion_tokens': 'completion_tokens',
           'total_tokens': 'total_tokens', 'provider_cost': 'cost'}


def begin_provider_usage():
    """Install a mutable request ledger inherited by child asyncio tasks."""
    return _entries.set([])


def end_provider_usage(token):
    """Restore the caller context after final persistence/stream cleanup."""
    _entries.reset(token)


@contextmanager
def stage_scope(stage):
    token = _stage.set(stage)
    try:
        yield
    finally:
        _stage.reset(token)


def _known(value):
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def _entry(router_type, model, values, stage, outcome):
    # Retain provider details for audit, but strip invalid numerical fields
    # before JSON persistence (NaN/Infinity are not valid JSON numbers).
    clean = {}
    if isinstance(values, dict):
        for name in _FIELDS.values():
            if _known(values.get(name)):
                clean[name] = values[name]
    return {'router_type': router_type, 'model': model, 'stage': stage,
            'outcome': outcome, 'usage': clean or None}


def record_usage(router_type, model, usage=None, stage=None, outcome='success'):
    """Record one observed HTTP attempt; absence of usage does not mean free."""
    entries = _entries.get()
    if entries is not None:
        entries.append(_entry(router_type, model, usage, stage or _stage.get(), outcome))


def _summarize(entries, scope):
    totals, coverage = {}, {}
    for output, field in _FIELDS.items():
        values = [entry['usage'][field] for entry in entries
                  if entry.get('usage') and field in entry['usage']]
        coverage[output] = len(values)
        totals[output] = sum(values) if values else None
    return {'entries': deepcopy(entries), 'totals': totals, 'coverage': coverage,
            'attempts': len(entries), 'scope': scope,
            'complete': bool(entries) and all(count == len(entries) for count in coverage.values())}


def get_provider_usage():
    """Snapshot all attempts observed in this request, including title/fallback."""
    return _summarize(_entries.get() or [], 'observed_provider_attempts')


def collect_provider_usage(stage1=None, stage2=None, stage3=None):
    """Fallback view from saved stage results; excludes title/lost attempts.

    Managed runs should persist get_provider_usage() instead for complete
    attempt coverage. This helper never claims a stage-only view is all usage.
    """
    entries = []
    for stage, results in [('STAGE1', stage1 or []), ('STAGE2', stage2 or []),
                           ('STAGE3', [stage3] if stage3 else [])]:
        for result in results:
            entries.append(_entry(result.get('router_type'), result.get('model'),
                                  result.get('usage'), stage,
                                  'error' if result.get('error') else 'success'))
    return _summarize(entries, 'stage_results_only')

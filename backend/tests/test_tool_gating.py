import json


class DummyTool:
    def __init__(self, name, *, run_result=None, invoke_result=None, run_raises=None, invoke_raises=None):
        self.name = name
        self._run_result = run_result
        self._invoke_result = invoke_result if invoke_result is not None else run_result
        self._run_raises = run_raises
        self._invoke_raises = invoke_raises

    def run(self, query):
        if self._run_raises:
            raise self._run_raises
        return self._run_result

    def invoke(self, query):
        if self._invoke_raises:
            raise self._invoke_raises
        return self._invoke_result


def test_exa_not_called_without_search_intent(monkeypatch):
    from .. import council as council_mod

    calculator = DummyTool("calculator", run_result="4")
    exa = DummyTool("exa_search", run_raises=AssertionError("Exa should not be called"))

    monkeypatch.setattr(council_mod, "get_available_tools", lambda: [calculator, exa])

    results = council_mod.run_tools_for_query("2+2")

    assert results
    assert results[0]["tool"] == "calculator"
    assert json.loads(results[0]["result"]) == "4"


def test_exa_called_only_with_search_intent(monkeypatch):
    from .. import council as council_mod

    exa = DummyTool("exa_search", invoke_result="exa ok")
    monkeypatch.setattr(council_mod, "get_available_tools", lambda: [exa])

    results = council_mod.run_tools_for_query("latest AI news")

    assert results == [{"tool": "exa_search", "result": json.dumps("exa ok", ensure_ascii=False)}]


def test_tavily_preferred_over_exa(monkeypatch):
    from .. import council as council_mod

    tavily = DummyTool("tavily_search", invoke_result=[{"title": "t"}])
    exa = DummyTool("exa_search", invoke_raises=AssertionError("Exa should not be called when Tavily exists"))

    monkeypatch.setattr(council_mod, "get_available_tools", lambda: [exa, tavily])

    results = council_mod.run_tools_for_query("latest AI news")

    assert results
    assert results[0]["tool"] == "tavily_search"
    assert json.loads(results[0]["result"]) == [{"title": "t"}]


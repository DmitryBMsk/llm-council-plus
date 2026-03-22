from backend.council import requires_tools


def test_requires_tools_does_not_trigger_on_generic_definition_phrase():
    # A generic "what is X" should not force tool usage by default.
    # It often leads to unnecessary web calls and worse UX.
    assert requires_tools("Что такое LLM-TTCC-TEAM-PRO?") is False


def test_requires_tools_triggers_on_explicit_research_keywords():
    assert requires_tools("Найди в Википедии информацию про Python") is True
    assert requires_tools("arxiv paper about transformers") is True


"""Stage 2 fairness: per-judge answer order and self-votes left out of the aggregate (#54)."""

import random
import re

import pytest

from .. import council

LABEL_TO_MODEL = {"Response A": "m1", "Response B": "m2", "Response C": "m3"}


def _ranking(judge, *letters):
    lines = "\n".join(f"{position}. Response {letter}" for position, letter in enumerate(letters, start=1))
    return {"model": judge, "ranking": f"Evaluation.\n\nFINAL RANKING:\n{lines}"}


def _aggregate(stage2_results, label_to_model=LABEL_TO_MODEL):
    return {row["model"]: row for row in council.calculate_aggregate_rankings(stage2_results, label_to_model)}


@pytest.mark.asyncio
async def test_each_judge_gets_its_own_answer_order(monkeypatch):
    prompts = {}

    async def fake_query(router_type, models, messages, **kwargs):
        prompts.update({model: messages[model][0]["content"] for model in models})
        return {model: {"content": "FINAL RANKING:\n1. Response A\n2. Response B\n3. Response C"} for model in models}

    monkeypatch.setattr(council.router_dispatch, "query_models_with_stage_timeout", fake_query)
    stage1 = [{"model": model, "response": f"answer-of-{model}"} for model in ("m1", "m2", "m3")]

    rankings, label_to_model = await council.stage2_collect_rankings(
        "question", stage1, models=["m1", "m2", "m3"], rng=random.Random(54),
    )

    assert set(prompts) == {"m1", "m2", "m3"}
    orders = set()
    for prompt in prompts.values():
        for answer in ("answer-of-m1", "answer-of-m2", "answer-of-m3"):
            assert prompt.count(answer) == 1
        for label, model in LABEL_TO_MODEL.items():
            # The label travels with its answer whatever the order.
            assert re.search(rf"{label}\W+answer-of-{model}\b", prompt)
        orders.add(tuple(sorted(LABEL_TO_MODEL.values(), key=lambda model: prompt.index(f"answer-of-{model}"))))
    assert len(orders) > 1, "every judge received the answers in the same order"
    # Labels stay tied to models for every judge, so stored rankings keep their meaning.
    assert label_to_model == LABEL_TO_MODEL
    assert [row["parsed_ranking"] for row in rankings] == [["Response A", "Response B", "Response C"]] * 3


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", ["openrouter", "ollama"])
async def test_provider_sends_each_model_its_own_messages(monkeypatch, provider_name):
    from .. import ollama, openrouter

    provider = {"openrouter": openrouter, "ollama": ollama}[provider_name]
    sent = {}

    async def fake_query_model(model, messages, **kwargs):
        sent[model] = messages
        return {"content": "ok"}

    monkeypatch.setattr(provider, "query_model", fake_query_model)
    per_model = {"m1": [{"role": "user", "content": "for m1"}], "m2": [{"role": "user", "content": "for m2"}]}

    await provider.query_models_with_stage_timeout(models=["m1", "m2"], messages=per_model, stage_timeout=5, min_results=2)

    assert sent == per_model


def test_aggregate_leaves_out_each_judges_vote_for_itself():
    # Every judge puts its own answer first.
    aggregate = _aggregate([
        _ranking("m1", "A", "B", "C"),
        _ranking("m2", "B", "A", "C"),
        _ranking("m3", "C", "A", "B"),
    ])

    assert {model: (row["average_rank"], row["rankings_count"]) for model, row in aggregate.items()} == {
        "m1": (1.0, 2),
        "m2": (1.5, 2),
        "m3": (2.0, 2),
    }
    assert all(row["self_votes_excluded"] is True for row in aggregate.values())


def test_where_a_judge_puts_itself_does_not_change_its_own_average():
    others = [_ranking("m2", "B", "A", "C"), _ranking("m3", "C", "A", "B")]

    first = _aggregate([_ranking("m1", "A", "B", "C"), *others])["m1"]
    last = _aggregate([_ranking("m1", "B", "C", "A"), *others])["m1"]

    assert first == last


def test_single_model_council_has_nothing_to_aggregate():
    assert council.calculate_aggregate_rankings([_ranking("m1", "A")], {"Response A": "m1"}) == []

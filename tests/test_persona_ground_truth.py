"""Persona ground truth must be self-consistent -- no key, no LLM calls.

A held-out persona is only worth running if its `expected_slots` are right.
An expectation written as "Bangalore" instead of "Bengaluru", or a domain
outside DOMAIN_TAGS, would score as a model failure when it is really a
typo in the answer key. These tests catch that class of error cheaply.

They deliberately do NOT check that the extractor agrees with the answer
key -- that is the measurement, and it needs a real API key.
"""

import pytest

from src.agent.slots import DOMAIN_TAGS, normalize_city, normalize_domain_tag
from src.sim.held_out_personas import HELD_OUT_IDS, HELD_OUT_PERSONAS
from src.sim.personas import PERSONAS

SLOT_KEYS = {"interested", "yoe", "domain", "city", "notice_period_days", "confirmed"}

_ALL = HELD_OUT_PERSONAS + [p for p in PERSONAS if p.expected_slots]


@pytest.mark.parametrize("persona", _ALL, ids=lambda p: f"{p.id}-{p.name}")
def test_expected_slots_use_the_six_known_keys(persona):
    assert set(persona.expected_slots) == SLOT_KEYS


@pytest.mark.parametrize("persona", _ALL, ids=lambda p: f"{p.id}-{p.name}")
def test_expected_domain_is_canonical(persona):
    domain = persona.expected_slots["domain"]
    if domain is None:
        return
    assert domain in DOMAIN_TAGS
    # canonical values must be fixed points of the normalizer
    assert normalize_domain_tag(domain) == domain


@pytest.mark.parametrize("persona", _ALL, ids=lambda p: f"{p.id}-{p.name}")
def test_expected_city_is_canonical(persona):
    city = persona.expected_slots["city"]
    if city is None:
        return
    assert normalize_city(city) == city, (
        f"{city!r} is not the canonical form -- the answer key would fail a "
        f"correct extraction (expected {normalize_city(city)!r})"
    )


@pytest.mark.parametrize("persona", _ALL, ids=lambda p: f"{p.id}-{p.name}")
def test_expected_types(persona):
    slots = persona.expected_slots
    assert slots["interested"] is None or isinstance(slots["interested"], bool)
    assert slots["confirmed"] is None or isinstance(slots["confirmed"], bool)
    assert slots["yoe"] is None or isinstance(slots["yoe"], float)
    assert slots["notice_period_days"] is None or isinstance(slots["notice_period_days"], int)


def test_persona_ids_are_unique_and_held_out_set_is_disjoint():
    ids = [p.id for p in HELD_OUT_PERSONAS] + [p.id for p in PERSONAS]
    assert len(ids) == len(set(ids))
    assert HELD_OUT_IDS.isdisjoint({p.id for p in PERSONAS})


def test_every_persona_has_replies():
    """No reply-count floor: a multi-slot reply ("yes, 4 years, Mumbai")
    fills three slots at once, so 4 replies can legitimately cover all six."""
    for persona in _ALL:
        assert persona.replies, f"{persona.name} has no replies"


def test_held_out_set_is_large_enough_to_read_something_into():
    """5 was too thin to draw conclusions from; keep it from silently shrinking."""
    assert len(HELD_OUT_PERSONAS) >= 12

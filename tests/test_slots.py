import pytest

from src.agent.slots import (
    DOMAIN_TAGS,
    first_unfilled_slot,
    normalize_bool,
    normalize_city,
    normalize_domain_tag,
    normalize_notice_period_days,
    normalize_yoe,
)


@pytest.mark.parametrize("raw,expected", [
    ("4 saal", 4.0),
    ("four", 4.0),
    ("4.5", 4.5),
    ("around 5", 5.0),
    ("fresher", 0.0),
    (None, None),
    ("no idea", None),
])
def test_normalize_yoe(raw, expected):
    assert normalize_yoe(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("2 months", 60),
    ("3 months", 90),
    ("15 days left", 15),
    ("serving notice, 15 days left", 15),
    ("do mahine ka notice hai", 60),
    ("2 weeks", 14),
    ("immediate", 0),
    ("asap", 0),
    (None, None),
])
def test_normalize_notice_period_days(raw, expected):
    assert normalize_notice_period_days(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("bombay", "Mumbai"),
    ("mumbai", "Mumbai"),
    ("navi mumbai", "Navi Mumbai"),
    ("bangalore", "Bengaluru"),
    ("Pune", "Pune"),
    (None, None),
])
def test_normalize_city(raw, expected):
    assert normalize_city(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("I work in Java mostly", "Java"),
    ("Python", "Python"),
    ("I'm into backend systems", "Backend"),
    ("  JAVA  ", "Java"),  # casing/whitespace never reaches the grader
    ("java   developer", "Java"),
    ("reactjs", "JavaScript"),
    ("kubernetes and docker", "DevOps"),
    ("COBOL mainframe", "Other"),  # a real answer, just not a known tag
    (None, None),
    ("", None),
])
def test_normalize_domain_tag(raw, expected):
    assert normalize_domain_tag(raw) == expected


def test_domain_tag_is_always_one_of_the_canonical_list():
    for raw in ["Java", "python", "some obscure legacy language", "  "]:
        result = normalize_domain_tag(raw)
        assert result is None or result in DOMAIN_TAGS


@pytest.mark.parametrize("raw,expected", [
    ("yes", True),
    ("haan", True),
    ("no", False),
    ("nahi", False),
    (True, True),
    ("maybe", None),
])
def test_normalize_bool(raw, expected):
    assert normalize_bool(raw) == expected


def test_first_unfilled_slot_order():
    slots = {"interested": True, "yoe": None, "domain": None, "city": None,
              "notice_period_days": None, "confirmed": None}
    assert first_unfilled_slot(slots) == "yoe"


def test_first_unfilled_slot_after():
    slots = {"interested": True, "yoe": 4.0, "domain": "Java", "city": None,
              "notice_period_days": None, "confirmed": None}
    assert first_unfilled_slot(slots, after="domain") == "city"


def test_first_unfilled_slot_none_left():
    slots = dict.fromkeys(["interested", "yoe", "domain", "city", "notice_period_days", "confirmed"], "x")
    assert first_unfilled_slot(slots) is None

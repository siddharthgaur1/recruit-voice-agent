"""Slot definitions, fixed order, questions, and normalisation.

These are pure functions with no LLM or I/O dependency, so they can be
pinned down and tested before any model is involved.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

_WORD_NUMBERS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20,
    # common Hinglish number words
    "ek": 1, "do": 2, "teen": 3, "char": 4, "paanch": 5, "panch": 5,
    "che": 6, "chhe": 6, "saat": 7, "aath": 8, "nau": 9, "das": 10,
}

_CITY_ALIASES = {
    "bombay": "Mumbai", "mumbai": "Mumbai", "navi mumbai": "Navi Mumbai",
    "bangalore": "Bengaluru", "bengaluru": "Bengaluru",
    "gurgaon": "Gurugram", "gurugram": "Gurugram",
    "calcutta": "Kolkata", "kolkata": "Kolkata",
    "madras": "Chennai", "chennai": "Chennai",
    "delhi": "Delhi", "new delhi": "Delhi",
    "poona": "Pune", "pune": "Pune",
    "hyderabad": "Hyderabad", "noida": "Noida",
}

_DOMAIN_FILLER_PATTERNS = [
    re.compile(r"^i\s+work\s+(in|with|on)\s+", re.IGNORECASE),
    re.compile(r"^i'?m\s+(in|into)\s+", re.IGNORECASE),
    re.compile(r"^mostly\s+", re.IGNORECASE),
    re.compile(r"\s+mostly$", re.IGNORECASE),
    re.compile(r"^primarily\s+", re.IGNORECASE),
    re.compile(r"\s+primarily$", re.IGNORECASE),
    re.compile(r"^i\s+do\s+", re.IGNORECASE),
]

_NOTICE_UNIT_TO_DAYS = {
    "day": 1, "days": 1, "din": 1, "dino": 1,
    "week": 7, "weeks": 7, "hafte": 7, "hafta": 7,
    "month": 30, "months": 30, "mahine": 30, "mahina": 30, "maheena": 30,
    "year": 365, "years": 365, "saal": 365, "varsh": 365,
}

_NUMBER_ALTERNATION = "|".join(sorted(_WORD_NUMBERS, key=len, reverse=True))
_UNIT_ALTERNATION = "|".join(sorted(_NOTICE_UNIT_TO_DAYS, key=len, reverse=True))
_NOTICE_QTY_UNIT_RE = re.compile(
    rf"(\d+(?:\.\d+)?|{_NUMBER_ALTERNATION})\s*({_UNIT_ALTERNATION})\b"
)


def _parse_qty(token: str) -> float:
    if re.fullmatch(r"\d+(\.\d+)?", token):
        return float(token)
    return float(_WORD_NUMBERS[token])


def normalize_yoe(raw: Any) -> float | None:
    """'4 saal', 'four', '4.5', 'around 5', 'fresher' -> float years."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip().lower()
    if not text:
        return None
    if "fresher" in text or "no experience" in text or "fresh graduate" in text:
        return 0.0
    match = re.search(r"\d+(\.\d+)?", text)
    if match:
        return float(match.group())
    for word, value in _WORD_NUMBERS.items():
        if re.search(rf"\b{word}\b", text):
            return float(value)
    return None


def normalize_notice_period_days(raw: Any) -> int | None:
    """'2 months' -> 60, '15 days left' -> 15, 'immediate' -> 0. Always days."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return int(raw)
    text = str(raw).strip().lower()
    if not text:
        return None

    match = _NOTICE_QTY_UNIT_RE.search(text)
    if match:
        qty = _parse_qty(match.group(1))
        unit = match.group(2)
        return int(round(qty * _NOTICE_UNIT_TO_DAYS[unit]))

    # a bare number with no unit -> assume days
    bare = re.search(r"\b(\d+)\b", text)
    if bare:
        return int(bare.group(1))

    if any(kw in text for kw in ("immediate", "immediately", "asap", "right away")):
        return 0

    return None


def normalize_city(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    canonical = _CITY_ALIASES.get(text.lower())
    if canonical:
        return canonical
    return text.title()


def _clean_domain_text(raw: Any) -> str | None:
    """Strip filler phrases and collapse casing/whitespace -- this text
    should never reach the grader un-normalized."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    for pattern in _DOMAIN_FILLER_PATTERNS:
        text = pattern.sub("", text)
    text = re.sub(r"\s+", " ", text).strip().strip(".").strip()
    return text or None


# Canonical domain vocabulary. candidate_profiles.domain is always one of
# these (never raw free text) so "Java candidates" is a real, exact-match
# query -- the original wording is preserved separately for humans to read.
DOMAIN_TAGS = [
    "Java", "Python", "JavaScript", "DevOps", "Data Science", "QA/Testing",
    "Cloud", "Mobile", "Backend", "Frontend", "Full Stack", "Other",
]

_DOMAIN_ALIASES = {
    "java": "Java", "j2ee": "Java", "spring": "Java", "spring boot": "Java",
    "python": "Python", "django": "Python", "flask": "Python",
    "javascript": "JavaScript", "js": "JavaScript", "typescript": "JavaScript",
    "node": "JavaScript", "nodejs": "JavaScript", "node.js": "JavaScript",
    "react": "JavaScript", "reactjs": "JavaScript", "react.js": "JavaScript",
    "vue": "JavaScript", "angular": "JavaScript",
    "devops": "DevOps", "sre": "DevOps", "kubernetes": "DevOps", "k8s": "DevOps",
    "docker": "DevOps", "ci/cd": "DevOps", "cicd": "DevOps",
    "data science": "Data Science", "machine learning": "Data Science",
    "ml": "Data Science", "ai": "Data Science", "data scientist": "Data Science",
    "data analytics": "Data Science", "data analyst": "Data Science",
    "qa": "QA/Testing", "testing": "QA/Testing", "quality assurance": "QA/Testing",
    "test automation": "QA/Testing", "sdet": "QA/Testing",
    "cloud": "Cloud", "aws": "Cloud", "azure": "Cloud", "gcp": "Cloud",
    "mobile": "Mobile", "android": "Mobile", "ios": "Mobile", "flutter": "Mobile",
    "react native": "Mobile",
    "backend": "Backend", "back-end": "Backend", "back end": "Backend",
    "frontend": "Frontend", "front-end": "Frontend", "front end": "Frontend",
    "full stack": "Full Stack", "fullstack": "Full Stack", "full-stack": "Full Stack",
}

_DOMAIN_ALIAS_TOKEN_RE = re.compile(r"[a-z0-9+#.]+")


def normalize_domain_tag(raw: Any) -> str | None:
    """Map free text to a canonical DOMAIN_TAGS entry. Returns None only for
    empty input (nothing was said); anything non-empty that doesn't match a
    known alias still resolves to "Other" -- a real answer was given, it
    just isn't one of our recognized tags, so the slot must not be treated
    as unanswered (that raw text is preserved separately, see domain_raw)."""
    cleaned = _clean_domain_text(raw)
    if cleaned is None:
        return None
    key = cleaned.lower().strip()
    if key in _DOMAIN_ALIASES:
        return _DOMAIN_ALIASES[key]
    for token in _DOMAIN_ALIAS_TOKEN_RE.findall(key):
        if token in _DOMAIN_ALIASES:
            return _DOMAIN_ALIASES[token]
    return "Other"


_TRUE_WORDS = {
    "yes", "yeah", "yep", "yup", "sure", "haan", "ha", "haanji", "ji",
    "bilkul", "zaroor", "correct", "true", "definitely", "ok", "okay",
}
_FALSE_WORDS = {
    "no", "nope", "nah", "nahi", "nahin", "na", "not interested", "false",
}


def normalize_bool(raw: Any) -> bool | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in _TRUE_WORDS:
        return True
    if text in _FALSE_WORDS:
        return False
    # A single yes/no token wrapped in filler ("yeah sure", "haan ji bilkul")
    # still counts, as long as it's not contradicted by an opposite token.
    tokens = set(re.findall(r"[a-z]+", text))
    is_true = bool(tokens & _TRUE_WORDS)
    is_false = bool(tokens & _FALSE_WORDS)
    if is_true and not is_false:
        return True
    if is_false and not is_true:
        return False
    return None


@dataclass(frozen=True)
class Slot:
    name: str
    type: type
    question: str  # may reference {company}
    normalize: Callable[[Any], Any]


SLOTS: list[Slot] = [
    Slot(
        "interested", bool,
        "Great to connect! Are you currently exploring a job switch? "
        "We have some strong openings at {company}.",
        normalize_bool,
    ),
    Slot(
        "yoe", float,
        "Wonderful. How many years of experience do you have?",
        normalize_yoe,
    ),
    Slot(
        "domain", str,
        "And which domain or tech stack do you primarily work in?",
        normalize_domain_tag,
    ),
    Slot(
        "city", str,
        "Which city are you based in?",
        normalize_city,
    ),
    Slot(
        "notice_period_days", int,
        "What's your notice period?",
        normalize_notice_period_days,
    ),
    Slot(
        "confirmed", bool,
        "We have an opening at {company} with strong hike potential. "
        "Shall I send you the details on WhatsApp?",
        normalize_bool,
    ),
]

SLOT_ORDER = [s.name for s in SLOTS]
SLOTS_BY_NAME = {s.name: s for s in SLOTS}


def first_unfilled_slot(slots: dict[str, Any], after: str | None = None) -> str | None:
    """Next slot in fixed order that is still None, optionally starting after a given slot."""
    order = SLOT_ORDER
    if after is not None:
        idx = order.index(after)
        order = order[idx + 1:]
    for name in order:
        if slots.get(name) is None:
            return name
    return None

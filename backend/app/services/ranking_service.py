"""
RankingService
---------------
Pure, provider-independent logic that sits between AIService's raw candidate
pool and the trademark/domain screening steps:

  large candidate pool -> quality filter -> duplicate filter -> rank

Screening (trademark/domain) happens afterwards in the route layer, then
this module's `final_sort` re-ranks using screening results too.
"""

import re
from difflib import SequenceMatcher
from typing import List

from app.services.ai_service import NameCandidate

BANNED_SUBSTRINGS = {"inc", "corp", "llc", "ltd"}  # legal suffixes don't belong in a brand name candidate
MIN_LEN, MAX_LEN = 3, 30


def _is_quality_candidate(candidate: NameCandidate) -> bool:
    name = candidate.name.strip()
    if not (MIN_LEN <= len(name) <= MAX_LEN):
        return False
    if not re.match(r"^[A-Za-z0-9&' \-]+$", name):
        return False
    lowered = name.lower()
    if any(bad in lowered.split() for bad in BANNED_SUBSTRINGS):
        return False
    if candidate.brandability_score < 20:
        return False
    return True


def quality_filter(candidates: List[NameCandidate]) -> List[NameCandidate]:
    return [c for c in candidates if _is_quality_candidate(c)]


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def duplicate_filter(candidates: List[NameCandidate], similarity_threshold: float = 0.92) -> List[NameCandidate]:
    kept: List[NameCandidate] = []
    seen_norms = []
    for c in candidates:
        norm = _normalize(c.name)
        if not norm:
            continue
        is_dupe = False
        for existing_norm in seen_norms:
            if norm == existing_norm:
                is_dupe = True
                break
            if SequenceMatcher(None, norm, existing_norm).ratio() >= similarity_threshold:
                is_dupe = True
                break
        if not is_dupe:
            kept.append(c)
            seen_norms.append(norm)
    return kept


def initial_rank(candidates: List[NameCandidate]) -> List[NameCandidate]:
    return sorted(candidates, key=lambda c: c.brandability_score, reverse=True)


def advanced_filter(candidates: List[NameCandidate], advanced: dict = None) -> List[NameCandidate]:
    """Defense-in-depth on top of the prompt instructions: hard-excludes any
    candidate that contains a user-specified 'word to avoid' or exactly
    matches a 'disliked name', in case the model doesn't fully comply."""
    if not advanced:
        return candidates
    avoid_words = [w.lower() for w in (advanced.get("words_to_avoid") or []) if w]
    disliked = [n.lower() for n in (advanced.get("names_disliked") or []) if n]
    if not avoid_words and not disliked:
        return candidates
    kept = []
    for c in candidates:
        lname = c.name.lower()
        if any(w in lname for w in avoid_words):
            continue
        if lname in disliked:
            continue
        kept.append(c)
    return kept


TRADEMARK_RISK_PENALTY = {
    "Low Risk": 0,
    "Medium Risk": -8,
    "High Risk": -25,
    "Search Failed": -3,
    "Needs Manual Review": -3,
}


def final_sort(scored_names: List[dict]) -> List[dict]:
    """scored_names: list of dicts with brandability_score, trademark_status,
    and domain_status (dict of tld -> available/taken/unavailable)."""

    def score(entry):
        base = entry.get("brandability_score", 0)
        base += TRADEMARK_RISK_PENALTY.get(entry.get("trademark_status"), -3)
        domain_status = entry.get("domain_status") or {}
        available_coms = 1 if domain_status.get("com") == "available" else 0
        base += available_coms * 5
        return base

    ranked = sorted(scored_names, key=score, reverse=True)
    for i, entry in enumerate(ranked, start=1):
        entry["rank"] = i
    return ranked

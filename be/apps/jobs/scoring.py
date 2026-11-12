"""Versioned match score. This is not a probability and it never uses protected characteristics."""

from __future__ import annotations

SCORE_VERSION = "sable-score-v1"
RRF_K = 60
WEIGHTS = {
    "mandatory": 50,
    "preferred": 20,
    "experience": 10,
    "title": 8,
    "location": 7,
    "retrieval": 5,
}


def reciprocal_rank_fusion(rankings: list[list], k: int = RRF_K) -> dict:
    scores: dict = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return scores


def component_ratio(met: int, unmet: int, weight: float) -> float | None:
    known = met + unmet
    if known == 0:
        return None
    return weight * (met / known)


def finalize_score(parts: list[tuple[str, float | None]]) -> float:
    applicable = [(name, value) for name, value in parts if value is not None]
    if not applicable:
        return 0.0
    weight_sum = sum(WEIGHTS[name] for name, _value in applicable)
    earned = sum(value for _name, value in applicable)
    if weight_sum <= 0:
        return 0.0
    return round(max(0.0, min(100.0, 100.0 * earned / weight_sum)), 2)

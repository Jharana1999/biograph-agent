from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RankWeights:
    association_score: float = 0.55
    evidence_count: float = 0.25
    known_drugs: float = 0.20


def score_target(*, ot_score: float | None, evidence_count: int | None, known_drug_count: int, w: RankWeights) -> float:
    s = 0.0
    if ot_score is not None:
        s += w.association_score * float(ot_score)
    if evidence_count is not None:
        s += w.evidence_count * (min(200, int(evidence_count)) / 200.0)
    if known_drug_count:
        s += w.known_drugs * (min(10, int(known_drug_count)) / 10.0)
    return round(s, 6)


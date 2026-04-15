from __future__ import annotations

from pydantic import BaseModel, Field


class Citation(BaseModel):
    source: str = Field(..., examples=["OpenTargets", "UniProt", "Ensembl", "PubMed"])
    id: str = Field(..., examples=["PMID:123456", "ENSG00000142192", "P05067"])
    title: str | None = None
    url: str | None = None


class EvidenceItem(BaseModel):
    evidence_id: str
    target_id: str
    disease_id: str
    score: float | None = None
    datasource: str | None = None
    description: str | None = None
    citations: list[Citation] = []


class RankedTarget(BaseModel):
    target_id: str
    target_symbol: str | None = None
    target_name: str | None = None
    score: float
    rationale: list[str] = []
    top_evidence: list[EvidenceItem] = []


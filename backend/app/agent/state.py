from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.schemas.common import RankedTarget, Citation, EvidenceItem


@dataclass
class AgentState:
    question: str
    run_id: str

    # Scope gating
    rejected: bool = False

    disease_query: str | None = None
    disease_id: str | None = None
    disease_name: str | None = None

    plan_steps: list[str] = field(default_factory=list)

    # Raw fetched data (for eval + traceability)
    ot_disease_hits: list[dict[str, Any]] = field(default_factory=list)
    ot_associations: list[dict[str, Any]] = field(default_factory=list)
    ot_known_drugs: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    ensembl_genes: dict[str, dict[str, Any]] = field(default_factory=dict)
    uniprot_proteins: dict[str, dict[str, Any]] = field(default_factory=dict)
    pubmed_summaries: dict[str, Any] = field(default_factory=dict)

    # Derived
    ranked_targets: list[RankedTarget] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)

    # Graph write stats
    graph_nodes_added: int = 0
    graph_edges_added: int = 0

    # Graph snapshot returned to frontend
    graph_nodes: list[dict[str, Any]] = field(default_factory=list)
    graph_edges: list[dict[str, Any]] = field(default_factory=list)

    answer_markdown: str | None = None
    evaluation: dict[str, Any] = field(default_factory=dict)


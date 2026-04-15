from __future__ import annotations

import uuid
from typing import Any

import httpx
from langgraph.graph import StateGraph, END
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph_writer import GraphWriter
from app.agent.ranking import RankWeights, score_target
from app.agent.state import AgentState
from app.agent.tools import log_tool_call, stable_id
from app.core.config import settings
from app.db.neo4j import get_driver
from app.integrations.ensembl import EnsemblClient
from app.integrations.opentargets import OpenTargetsClient
from app.integrations.pubmed import PubMedClient
from app.integrations.uniprot import UniProtClient
from app.schemas.common import Citation, RankedTarget, EvidenceItem


_http: httpx.AsyncClient | None = None
_pg: AsyncSession | None = None


def new_run_id() -> str:
    return uuid.uuid4().hex[:16]


# ---------------------------------------------------------------------------
# Node 1 – Plan
# ---------------------------------------------------------------------------
async def node_plan(state: AgentState) -> AgentState:
    state.plan_steps = [
        "Extract the disease entity from the user question.",
        "Search and resolve the disease entity (Open Targets).",
        "Fetch disease → target associations (Open Targets).",
        "Enrich targets with known drug links (Open Targets).",
        "Resolve gene details for top targets (Ensembl).",
        "Resolve protein accessions for top targets (UniProt).",
        "Fetch supporting publications (PubMed) for top targets.",
        "Build / update a Neo4j knowledge graph.",
        "Rank targets and generate an evidence-backed scientific summary.",
        "Run automated quality checks (citations, hallucination risk, validation).",
    ]
    return state


# ---------------------------------------------------------------------------
# Node 2 – Scope check + disease extraction (single LLM call)
# ---------------------------------------------------------------------------
_SCOPE_PROMPT = """You classify biomedical research queries.

Analyze the user's question and respond in exactly ONE of these formats:

DISEASE: <disease or condition name>
  Use this if the question is about drug targets, diseases, genes, proteins,
  biomedical research, pharmacology, or any health/medical topic.

OUT_OF_SCOPE
  Use this if the question is completely unrelated to biomedical science.

Examples:
"Find drug targets for Alzheimer's disease" → DISEASE: Alzheimer's disease
"What genes are linked to breast cancer?" → DISEASE: breast cancer
"Tell me about Nepali festivals" → OUT_OF_SCOPE
"What is the capital of France?" → OUT_OF_SCOPE
"""


async def node_extract_disease(state: AgentState) -> AgentState:
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    resp = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": _SCOPE_PROMPT},
            {"role": "user", "content": state.question},
        ],
        temperature=0.0,
        max_tokens=60,
    )
    raw = (resp.choices[0].message.content or "").strip()

    if raw.upper().startswith("OUT_OF_SCOPE"):
        state.rejected = True
        return state

    if raw.upper().startswith("DISEASE:"):
        extracted = raw.split(":", 1)[1].strip().strip('"').strip("'")
    else:
        extracted = raw.strip().strip('"').strip("'")

    if not extracted or extracted.lower() == "unknown":
        state.rejected = True
        return state

    state.disease_query = extracted
    return state


# ---------------------------------------------------------------------------
# Node 2b – Out-of-scope response (only reached via conditional edge)
# ---------------------------------------------------------------------------
_OUT_OF_SCOPE_MD = """\
## Out of Scope

This agent specializes in **biomedical target discovery** — identifying and \
ranking potential drug targets for diseases using evidence from Open Targets, \
Ensembl, UniProt, and PubMed.

Your question doesn't appear to be about biomedical research or drug discovery.

### Try questions like
- "Find drug targets for Alzheimer's disease"
- "What are the most promising therapeutic targets for Type 2 diabetes?"
- "Identify potential drug targets for Parkinson's disease"
- "What genes are associated with breast cancer and could be drug targets?"
"""


async def node_reject_response(state: AgentState) -> AgentState:
    state.answer_markdown = _OUT_OF_SCOPE_MD
    state.evaluation = {
        "passed": False,
        "checks": {
            "scope": {
                "label": "Query Scope",
                "description": "Question was not recognized as a biomedical research query",
                "value": "out_of_scope",
                "pass": False,
            },
        },
        "notes": None,
    }
    return state


# ---------------------------------------------------------------------------
# Node 3 – Search disease on Open Targets
# ---------------------------------------------------------------------------
async def node_search_disease(state: AgentState) -> AgentState:
    http, pg = _http, _pg
    assert http and pg
    ot = OpenTargetsClient(http)
    hits = await ot.search_disease(state.disease_query or state.question, size=5)
    state.ot_disease_hits = hits
    await log_tool_call(
        pg,
        run_id=state.run_id,
        tool_name="opentargets.search_disease",
        request={"q": state.disease_query},
        response={"hits": hits},
        ok=True,
    )

    best = hits[0] if hits else None
    if best:
        state.disease_id = best.get("id")
        state.disease_name = best.get("name")
        state.citations.append(
            Citation(
                source="OpenTargets",
                id=state.disease_id or "unknown",
                title=state.disease_name,
                url=f"https://platform.opentargets.org/disease/{state.disease_id}",
            )
        )
    return state


# ---------------------------------------------------------------------------
# Node 4 – Fetch associations
# ---------------------------------------------------------------------------
async def node_fetch_associations(state: AgentState) -> AgentState:
    if not state.disease_id:
        return state
    http, pg = _http, _pg
    assert http and pg
    ot = OpenTargetsClient(http)
    rows = await ot.disease_associations(state.disease_id, size=25)
    state.ot_associations = rows
    await log_tool_call(
        pg,
        run_id=state.run_id,
        tool_name="opentargets.disease_associations",
        request={"disease_id": state.disease_id},
        response={"count": len(rows)},
        ok=True,
    )
    return state


# ---------------------------------------------------------------------------
# Node 5 – Enrich with known drugs
# ---------------------------------------------------------------------------
async def node_enrich_known_drugs(state: AgentState) -> AgentState:
    http, pg = _http, _pg
    assert http and pg
    ot = OpenTargetsClient(http)
    for row in state.ot_associations[:15]:
        target = row.get("target") or {}
        tid = target.get("id")
        if not tid:
            continue
        try:
            drugs = await ot.target_known_drugs(tid, size=10)
        except Exception:
            drugs = []
        state.ot_known_drugs[tid] = drugs
        await log_tool_call(
            pg,
            run_id=state.run_id,
            tool_name="opentargets.target_known_drugs",
            request={"target_id": tid},
            response={"count": len(drugs)},
            ok=len(drugs) > 0,
        )
    return state


# ---------------------------------------------------------------------------
# Node 6 – Resolve genes via Ensembl
# ---------------------------------------------------------------------------
async def node_resolve_genes(state: AgentState) -> AgentState:
    http, pg = _http, _pg
    assert http and pg
    ens = EnsemblClient(http)
    seen: set[str] = set()
    for row in state.ot_associations[:10]:
        tid = (row.get("target") or {}).get("id")
        if not tid or tid in seen or not tid.startswith("ENSG"):
            continue
        seen.add(tid)
        try:
            gene = await ens.lookup_gene(tid)
        except Exception:
            gene = None
        if gene and isinstance(gene, dict):
            state.ensembl_genes[tid] = gene
            state.citations.append(
                Citation(
                    source="Ensembl",
                    id=tid,
                    title=gene.get("display_name") or gene.get("id"),
                    url=f"https://ensembl.org/Homo_sapiens/Gene/Summary?g={tid}",
                )
            )
            await log_tool_call(
                pg,
                run_id=state.run_id,
                tool_name="ensembl.lookup_gene",
                request={"ensembl_id": tid},
                response={"display_name": gene.get("display_name"), "biotype": gene.get("biotype")},
                ok=True,
            )
        else:
            await log_tool_call(
                pg,
                run_id=state.run_id,
                tool_name="ensembl.lookup_gene",
                request={"ensembl_id": tid},
                response={},
                ok=False,
            )
    return state


# ---------------------------------------------------------------------------
# Node 7 – Resolve proteins via UniProt
# ---------------------------------------------------------------------------
async def node_resolve_proteins(state: AgentState) -> AgentState:
    http, pg = _http, _pg
    assert http and pg
    up = UniProtClient(http)
    for tid, gene in list(state.ensembl_genes.items())[:10]:
        accession = _extract_uniprot_accession(gene)
        if not accession:
            continue
        try:
            protein = await up.get_protein(accession)
        except Exception:
            protein = None
        if protein:
            state.uniprot_proteins[tid] = protein
            pname = _uniprot_protein_name(protein)
            state.citations.append(
                Citation(
                    source="UniProt",
                    id=accession,
                    title=pname,
                    url=f"https://www.uniprot.org/uniprotkb/{accession}",
                )
            )
        await log_tool_call(
            pg,
            run_id=state.run_id,
            tool_name="uniprot.get_protein",
            request={"accession": accession, "target_id": tid},
            response={"found": protein is not None},
            ok=protein is not None,
        )
    return state


def _extract_uniprot_accession(gene: dict[str, Any]) -> str | None:
    for xref in gene.get("xrefs", []):
        if xref.get("dbname") == "Uniprot/SWISSPROT":
            return xref.get("primary_id")
    return None


def _uniprot_protein_name(protein: dict[str, Any]) -> str:
    try:
        return protein["proteinDescription"]["recommendedName"]["fullName"]["value"]
    except (KeyError, TypeError):
        return protein.get("primaryAccession", "")


# ---------------------------------------------------------------------------
# Node 8 – PubMed evidence
# ---------------------------------------------------------------------------
async def node_pubmed_for_top_targets(state: AgentState) -> AgentState:
    if not state.disease_name:
        return state
    http, pg = _http, _pg
    assert http and pg
    pm = PubMedClient(http)
    top_symbols: list[str] = []
    for row in state.ot_associations[:8]:
        sym = (row.get("target") or {}).get("approvedSymbol")
        if sym:
            top_symbols.append(sym)
    if top_symbols:
        term = (
            f"{state.disease_name} "
            + " OR ".join(f"{s}[Title/Abstract]" for s in top_symbols[:3])
        )
    else:
        term = state.disease_name

    pmids = await pm.esearch(term, retmax=6)
    summary = await pm.esummary(pmids)
    state.pubmed_summaries = summary
    await log_tool_call(
        pg,
        run_id=state.run_id,
        tool_name="pubmed.esearch",
        request={"term": term},
        response={"pmids": pmids},
        ok=True,
    )

    result = summary.get("result", {}) if isinstance(summary, dict) else {}
    for pid in pmids:
        doc = result.get(pid)
        if not doc:
            continue
        title = doc.get("title")
        url = f"https://pubmed.ncbi.nlm.nih.gov/{pid}/"
        state.citations.append(
            Citation(source="PubMed", id=f"PMID:{pid}", title=title, url=url)
        )
    return state


# ---------------------------------------------------------------------------
# Node 9 – Rank targets
# ---------------------------------------------------------------------------
async def node_rank(state: AgentState) -> AgentState:
    w = RankWeights()
    ranked: list[RankedTarget] = []
    for row in state.ot_associations:
        t = row.get("target") or {}
        tid = t.get("id")
        if not tid:
            continue
        known = state.ot_known_drugs.get(tid, [])
        gene_info = state.ensembl_genes.get(tid)
        protein_info = state.uniprot_proteins.get(tid)

        s = score_target(
            ot_score=row.get("score"),
            evidence_count=row.get("evidenceCount"),
            known_drug_count=len(known),
            w=w,
        )

        rationale: list[str] = []
        if row.get("score") is not None:
            rationale.append(f"Open Targets association score: {row['score']:.3f}")
        if row.get("evidenceCount") is not None:
            rationale.append(f"Evidence count: {row['evidenceCount']}")
        if known:
            rationale.append(f"Known drugs linked: {len(known)}")
        if gene_info:
            biotype = gene_info.get("biotype", "")
            if biotype:
                rationale.append(f"Gene biotype: {biotype}")
        if protein_info:
            rationale.append("UniProt protein record available")

        ev = EvidenceItem(
            evidence_id=stable_id("ot", state.disease_id or "", tid),
            target_id=tid,
            disease_id=state.disease_id or "unknown",
            score=row.get("score"),
            datasource="OpenTargets",
            description="Disease-target association (Open Targets).",
            citations=[
                Citation(
                    source="OpenTargets",
                    id=tid,
                    title=t.get("approvedName") or t.get("approvedSymbol"),
                    url=f"https://platform.opentargets.org/target/{tid}",
                )
            ],
        )
        ranked.append(
            RankedTarget(
                target_id=tid,
                target_symbol=t.get("approvedSymbol"),
                target_name=t.get("approvedName"),
                score=s,
                rationale=rationale,
                top_evidence=[ev],
            )
        )
        state.evidence.append(ev)

    ranked.sort(key=lambda x: x.score, reverse=True)
    state.ranked_targets = ranked[:10]
    return state


# ---------------------------------------------------------------------------
# Node 10 – Build Neo4j graph + produce snapshot for frontend
# ---------------------------------------------------------------------------
async def node_build_graph(state: AgentState) -> AgentState:
    if not state.disease_id:
        return state
    pg = _pg
    assert pg
    driver = get_driver()
    writer = GraphWriter(driver)

    nodes_added = 0
    edges_added = 0

    dn, de = writer.upsert_disease(disease_id=state.disease_id, name=state.disease_name)
    nodes_added += dn
    edges_added += de

    for rt in state.ranked_targets:
        tn, te = writer.upsert_target(
            target_id=rt.target_id, symbol=rt.target_symbol, name=rt.target_name
        )
        nodes_added += tn
        edges_added += te

        en, ee = writer.link_disease_target(
            disease_id=state.disease_id,
            target_id=rt.target_id,
            props={
                "score": rt.score,
                "symbol": rt.target_symbol,
                "name": rt.target_name,
            },
        )
        nodes_added += en
        edges_added += ee

        gene = state.ensembl_genes.get(rt.target_id)
        if gene:
            gn, ge_ = writer.upsert_gene(
                gene_id=rt.target_id,
                symbol=gene.get("display_name"),
                biotype=gene.get("biotype"),
            )
            nodes_added += gn
            edges_added += ge_
            ln, le = writer.link_target_gene(
                target_id=rt.target_id, gene_id=rt.target_id
            )
            nodes_added += ln
            edges_added += le

        protein = state.uniprot_proteins.get(rt.target_id)
        if protein:
            acc = protein.get("primaryAccession", "")
            pn, pe = writer.upsert_protein(
                protein_id=acc, name=_uniprot_protein_name(protein)
            )
            nodes_added += pn
            edges_added += pe
            lpn, lpe = writer.link_gene_protein(gene_id=rt.target_id, protein_id=acc)
            nodes_added += lpn
            edges_added += lpe

        for kd in state.ot_known_drugs.get(rt.target_id, [])[:5]:
            drug = kd.get("drug") or {}
            did = drug.get("id")
            if not did:
                continue
            dn2, de2 = writer.upsert_drug(drug_id=did, name=drug.get("name"))
            nodes_added += dn2
            edges_added += de2
            en2, ee2 = writer.link_target_drug(
                target_id=rt.target_id,
                drug_id=did,
                props={"phase": kd.get("phase"), "status": kd.get("status")},
            )
            nodes_added += en2
            edges_added += ee2

    for cit in state.citations:
        if cit.source == "PubMed" and cit.id.startswith("PMID:"):
            pn2, pe2 = writer.upsert_publication(
                pub_id=cit.id, title=cit.title, url=cit.url
            )
            nodes_added += pn2
            edges_added += pe2

    driver.close()

    state.graph_nodes_added = nodes_added
    state.graph_edges_added = edges_added
    state.graph_nodes, state.graph_edges = _snapshot_graph(state)

    await log_tool_call(
        pg,
        run_id=state.run_id,
        tool_name="neo4j.build_graph",
        request={
            "disease_id": state.disease_id,
            "targets": [t.target_id for t in state.ranked_targets],
        },
        response={"nodes_added": nodes_added, "edges_added": edges_added},
        ok=True,
    )
    return state


def _snapshot_graph(state: AgentState) -> tuple[list[dict], list[dict]]:
    """Build a lightweight node/edge list for the frontend visualisation."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    node_ids: set[str] = set()

    def add_node(nid: str, label: str, name: str | None, **extra: Any) -> None:
        if nid in node_ids:
            return
        node_ids.add(nid)
        nodes.append({"id": nid, "label": label, "name": name or nid, **extra})

    if state.disease_id:
        add_node(state.disease_id, "Disease", state.disease_name)

    for rt in state.ranked_targets:
        add_node(
            rt.target_id,
            "Target",
            rt.target_symbol or rt.target_name,
            score=rt.score,
        )
        edges.append(
            {
                "source": state.disease_id,
                "target": rt.target_id,
                "type": "ASSOCIATED_WITH",
            }
        )

        gene = state.ensembl_genes.get(rt.target_id)
        if gene:
            gid = f"gene:{rt.target_id}"
            add_node(gid, "Gene", gene.get("display_name"))
            edges.append({"source": rt.target_id, "target": gid, "type": "HAS_GENE"})

        protein = state.uniprot_proteins.get(rt.target_id)
        if protein:
            acc = protein.get("primaryAccession", "")
            pid = f"protein:{acc}"
            add_node(pid, "Protein", _uniprot_protein_name(protein))
            gene_node = f"gene:{rt.target_id}" if gene else rt.target_id
            edges.append({"source": gene_node, "target": pid, "type": "ENCODES"})

        for kd in state.ot_known_drugs.get(rt.target_id, [])[:3]:
            drug = kd.get("drug") or {}
            did = drug.get("id")
            if did:
                add_node(did, "Drug", drug.get("name"))
                edges.append(
                    {"source": rt.target_id, "target": did, "type": "KNOWN_DRUG"}
                )

    for cit in state.citations:
        if cit.source == "PubMed":
            add_node(cit.id, "Publication", cit.title)

    return nodes, edges


# ---------------------------------------------------------------------------
# Node 11 – Generate explanation
# ---------------------------------------------------------------------------
async def node_generate_explanation(state: AgentState) -> AgentState:
    if not state.ranked_targets:
        if state.disease_query and not state.disease_id:
            state.answer_markdown = (
                f"## No Disease Match Found\n\n"
                f"I couldn't find **\"{state.disease_query}\"** in the Open Targets "
                f"database.\n\n"
                f"### Suggestions\n"
                f"- Try using a more specific disease name "
                f"(e.g., \"Alzheimer's disease\" instead of \"memory loss\")\n"
                f"- Check for spelling and use the standard disease name\n"
                f"- Try a broader category "
                f"(e.g., \"lung cancer\" instead of a rare subtype)\n"
            )
        else:
            state.answer_markdown = (
                "## No Targets Found\n\n"
                "The pipeline completed but did not identify any ranked targets "
                "for this query. This may happen for very rare diseases or "
                "conditions with limited data in Open Targets.\n"
            )
        return state

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    top = state.ranked_targets[:5]
    bullets = "\n".join(
        f"- {t.target_symbol or t.target_id}: score={t.score:.3f}" for t in top
    )
    gene_info = ""
    for t in top:
        g = state.ensembl_genes.get(t.target_id)
        p = state.uniprot_proteins.get(t.target_id)
        if g:
            gene_info += f"\n- {t.target_symbol}: biotype={g.get('biotype')}, description={g.get('description', 'N/A')}"
        if p:
            gene_info += f", UniProt accession={p.get('primaryAccession', 'N/A')}"

    citation_hint = "\n".join(
        f"- {c.source} {c.id} ({c.url})" for c in state.citations[:12]
    )
    prompt = f"""You are a biomedical research assistant. Write a concise scientific answer for:
{state.question}

Constraints:
- Base claims on the provided evidence list only.
- Include inline citations in brackets, e.g. [OpenTargets], [PubMed:PMID:12345], [Ensembl:ENSG00000142192].
- Use clean Markdown: ## for section headings, **bold** for gene symbols, numbered lists for ranked targets.
- Sections: Summary, Top Targets (ranked list with brief rationale each), Evidence Highlights, Limitations.

Top ranked targets:
{bullets}

Gene/protein enrichment:
{gene_info}

Available citations:
{citation_hint}"""

    resp = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": "You cite evidence and avoid speculation."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    state.answer_markdown = resp.choices[0].message.content or ""
    return state


# ---------------------------------------------------------------------------
# Node 12 – Evaluate
# ---------------------------------------------------------------------------
async def node_evaluate(state: AgentState) -> AgentState:
    pg = _pg
    assert pg
    text = (state.answer_markdown or "").lower()

    # --- Evidence Coverage ---------------------------------------------------
    # Real approach: check source-level grounding + key entity mentions.
    source_keywords: dict[str, list[str]] = {
        "OpenTargets": ["opentargets", "open targets"],
        "Ensembl": ["ensembl"],
        "UniProt": ["uniprot"],
        "PubMed": ["pubmed", "pmid"],
    }
    sources_queried = {c.source for c in state.citations}
    sources_cited = 0
    for src in sources_queried:
        kws = source_keywords.get(src, [src.lower()])
        if any(kw in text for kw in kws):
            sources_cited += 1

    top_n = min(5, len(state.ranked_targets))
    symbols_mentioned = sum(
        1
        for rt in state.ranked_targets[:5]
        if (rt.target_symbol or "").lower() in text
    )

    if sources_queried:
        src_ratio = sources_cited / len(sources_queried)
        sym_ratio = symbols_mentioned / top_n if top_n else 0
        evidence_score = round(0.6 * src_ratio + 0.4 * sym_ratio, 3)
    else:
        evidence_score = 0.0

    # --- API Success ---------------------------------------------------------
    api_results = {
        "Open Targets search": len(state.ot_disease_hits) > 0,
        "Target associations": len(state.ot_associations) > 0,
        "Ensembl genes": len(state.ensembl_genes) > 0,
        "UniProt proteins": len(state.uniprot_proteins) > 0,
    }
    api_ok = sum(v for v in api_results.values())

    # --- Graph Built ---------------------------------------------------------
    graph_ok = state.graph_nodes_added > 0 and state.graph_edges_added > 0

    checks: dict[str, Any] = {
        "evidence_coverage": {
            "label": "Evidence Coverage",
            "description": (
                f"{sources_cited}/{len(sources_queried)} data sources referenced in answer, "
                f"{symbols_mentioned}/{top_n} top targets mentioned"
            ),
            "value": evidence_score,
            "pass": evidence_score >= 0.4,
        },
        "api_success": {
            "label": "API Success",
            "description": f"{api_ok}/{len(api_results)} external APIs returned data",
            "value": api_results,
            "pass": api_ok >= 2,
        },
        "graph_built": {
            "label": "Graph Built",
            "description": (
                f"{state.graph_nodes_added} nodes and "
                f"{state.graph_edges_added} edges written to knowledge graph"
            ),
            "value": {
                "nodes": state.graph_nodes_added,
                "edges": state.graph_edges_added,
            },
            "pass": graph_ok,
        },
    }

    passed = all(v["pass"] for v in checks.values())
    state.evaluation = {"passed": passed, "checks": checks, "notes": None}

    from app.db.models import EvaluationResult

    row = EvaluationResult(
        run_id=state.run_id, checks=checks, passed=passed, notes=None
    )
    pg.add(row)
    await pg.commit()
    return state


# ---------------------------------------------------------------------------
# Graph builder + runner
# ---------------------------------------------------------------------------
def _route_after_extract(state: AgentState) -> str:
    return "reject" if state.rejected else "continue"


def build_langgraph() -> Any:
    g = StateGraph(AgentState)
    g.add_node("Plan", node_plan)
    g.add_node("ExtractDisease", node_extract_disease)
    g.add_node("RejectResponse", node_reject_response)
    g.add_node("SearchDisease", node_search_disease)
    g.add_node("FetchAssociations", node_fetch_associations)
    g.add_node("EnrichKnownDrugs", node_enrich_known_drugs)
    g.add_node("ResolveGenes", node_resolve_genes)
    g.add_node("ResolveProteins", node_resolve_proteins)
    g.add_node("PubMed", node_pubmed_for_top_targets)
    g.add_node("Rank", node_rank)
    g.add_node("BuildGraph", node_build_graph)
    g.add_node("GenerateExplanation", node_generate_explanation)
    g.add_node("Evaluate", node_evaluate)

    g.set_entry_point("Plan")
    g.add_edge("Plan", "ExtractDisease")
    g.add_conditional_edges(
        "ExtractDisease",
        _route_after_extract,
        {"reject": "RejectResponse", "continue": "SearchDisease"},
    )
    g.add_edge("RejectResponse", END)
    g.add_edge("SearchDisease", "FetchAssociations")
    g.add_edge("FetchAssociations", "EnrichKnownDrugs")
    g.add_edge("EnrichKnownDrugs", "ResolveGenes")
    g.add_edge("ResolveGenes", "ResolveProteins")
    g.add_edge("ResolveProteins", "PubMed")
    g.add_edge("PubMed", "Rank")
    g.add_edge("Rank", "BuildGraph")
    g.add_edge("BuildGraph", "GenerateExplanation")
    g.add_edge("GenerateExplanation", "Evaluate")
    g.add_edge("Evaluate", END)
    return g.compile()


async def run_agent(*, question: str, pg: AsyncSession) -> AgentState:
    global _http, _pg
    run_id = new_run_id()
    state = AgentState(question=question, run_id=run_id)
    graph = build_langgraph()
    async with httpx.AsyncClient(timeout=settings.http_timeout_s) as http:
        _http = http
        _pg = pg
        try:
            result = await graph.ainvoke(state)
        finally:
            _http = None
            _pg = None

    if isinstance(result, AgentState):
        return result
    # LangGraph may return AddableValuesDict; reconstruct AgentState
    if isinstance(result, dict):
        out = AgentState(
            question=result.get("question", question),
            run_id=result.get("run_id", run_id),
        )
        for field_name in AgentState.__dataclass_fields__:
            if field_name in ("question", "run_id"):
                continue
            if field_name in result:
                setattr(out, field_name, result[field_name])
        return out
    return state

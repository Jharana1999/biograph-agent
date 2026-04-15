from __future__ import annotations

from typing import Any

from neo4j import Driver


class GraphWriter:
    def __init__(self, driver: Driver):
        self.driver = driver

    # ── Disease ──────────────────────────────────────────────────────────
    def upsert_disease(self, *, disease_id: str, name: str | None) -> tuple[int, int]:
        q = """
        MERGE (d:Disease {id: $id})
        ON CREATE SET d.name = $name
        ON MATCH SET d.name = coalesce(d.name, $name)
        RETURN d.id as id
        """
        with self.driver.session() as s:
            s.run(q, id=disease_id, name=name)
        return (1, 0)

    # ── Target ───────────────────────────────────────────────────────────
    def upsert_target(self, *, target_id: str, symbol: str | None, name: str | None) -> tuple[int, int]:
        q = """
        MERGE (t:Target {id: $id})
        ON CREATE SET t.symbol = $symbol, t.name = $name
        ON MATCH SET t.symbol = coalesce(t.symbol, $symbol), t.name = coalesce(t.name, $name)
        RETURN t.id as id
        """
        with self.driver.session() as s:
            s.run(q, id=target_id, symbol=symbol, name=name)
        return (1, 0)

    def link_disease_target(self, *, disease_id: str, target_id: str, props: dict[str, Any]) -> tuple[int, int]:
        q = """
        MATCH (d:Disease {id: $disease_id})
        MATCH (t:Target {id: $target_id})
        MERGE (d)-[r:ASSOCIATED_WITH]->(t)
        SET r += $props
        """
        with self.driver.session() as s:
            s.run(q, disease_id=disease_id, target_id=target_id, props=props)
        return (0, 1)

    # ── Gene ─────────────────────────────────────────────────────────────
    def upsert_gene(self, *, gene_id: str, symbol: str | None, biotype: str | None) -> tuple[int, int]:
        q = """
        MERGE (g:Gene {id: $id})
        ON CREATE SET g.symbol = $symbol, g.biotype = $biotype
        ON MATCH SET g.symbol = coalesce(g.symbol, $symbol), g.biotype = coalesce(g.biotype, $biotype)
        """
        with self.driver.session() as s:
            s.run(q, id=gene_id, symbol=symbol, biotype=biotype)
        return (1, 0)

    def link_target_gene(self, *, target_id: str, gene_id: str) -> tuple[int, int]:
        q = """
        MATCH (t:Target {id: $target_id})
        MATCH (g:Gene {id: $gene_id})
        MERGE (t)-[r:HAS_GENE]->(g)
        """
        with self.driver.session() as s:
            s.run(q, target_id=target_id, gene_id=gene_id)
        return (0, 1)

    # ── Protein ──────────────────────────────────────────────────────────
    def upsert_protein(self, *, protein_id: str, name: str | None) -> tuple[int, int]:
        q = """
        MERGE (p:Protein {id: $id})
        ON CREATE SET p.name = $name
        ON MATCH SET p.name = coalesce(p.name, $name)
        """
        with self.driver.session() as s:
            s.run(q, id=protein_id, name=name)
        return (1, 0)

    def link_gene_protein(self, *, gene_id: str, protein_id: str) -> tuple[int, int]:
        q = """
        MATCH (g:Gene {id: $gene_id})
        MATCH (p:Protein {id: $protein_id})
        MERGE (g)-[r:ENCODES]->(p)
        """
        with self.driver.session() as s:
            s.run(q, gene_id=gene_id, protein_id=protein_id)
        return (0, 1)

    # ── Drug ─────────────────────────────────────────────────────────────
    def upsert_drug(self, *, drug_id: str, name: str | None) -> tuple[int, int]:
        q = """
        MERGE (x:Drug {id: $id})
        ON CREATE SET x.name = $name
        ON MATCH SET x.name = coalesce(x.name, $name)
        """
        with self.driver.session() as s:
            s.run(q, id=drug_id, name=name)
        return (1, 0)

    def link_target_drug(self, *, target_id: str, drug_id: str, props: dict[str, Any]) -> tuple[int, int]:
        q = """
        MATCH (t:Target {id: $target_id})
        MATCH (x:Drug {id: $drug_id})
        MERGE (t)-[r:KNOWN_DRUG]->(x)
        SET r += $props
        """
        with self.driver.session() as s:
            s.run(q, target_id=target_id, drug_id=drug_id, props=props)
        return (0, 1)

    # ── Publication ──────────────────────────────────────────────────────
    def upsert_publication(self, *, pub_id: str, title: str | None, url: str | None) -> tuple[int, int]:
        q = """
        MERGE (p:Publication {id: $id})
        ON CREATE SET p.title = $title, p.url = $url
        ON MATCH SET p.title = coalesce(p.title, $title), p.url = coalesce(p.url, $url)
        """
        with self.driver.session() as s:
            s.run(q, id=pub_id, title=title, url=url)
        return (1, 0)

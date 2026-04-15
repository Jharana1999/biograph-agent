from __future__ import annotations

import logging
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

OT_GRAPHQL = "https://api.platform.opentargets.org/api/v4/graphql"


class OpenTargetsClient:
    def __init__(self, http: httpx.AsyncClient):
        self.http = http

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        r = await self.http.post(OT_GRAPHQL, json={"query": query, "variables": variables or {}})
        r.raise_for_status()
        payload = r.json()
        if "errors" in payload:
            logger.warning("OpenTargets GraphQL errors: %s", payload["errors"])
            if "data" not in payload or payload["data"] is None:
                raise RuntimeError(f"OpenTargets GraphQL error: {payload['errors']}")
        return payload.get("data") or {}

    async def search_disease(self, text: str, size: int = 5) -> list[dict[str, Any]]:
        q = """
        query DiseaseSearch($q: String!, $size: Int!) {
          search(queryString: $q, entityNames: ["disease"], page: {index: 0, size: $size}) {
            hits {
              id
              name
              entity
              description
              score
            }
          }
        }
        """
        data = await self.graphql(q, {"q": text, "size": size})
        hits = data.get("search", {}).get("hits", []) or []
        return [h for h in hits if h.get("entity") == "disease"]

    async def disease_associations(self, disease_id: str, size: int = 25) -> list[dict[str, Any]]:
        q = """
        query DiseaseAssociations($diseaseId: String!, $size: Int!) {
          disease(efoId: $diseaseId) {
            id
            name
            associatedTargets(page: {index: 0, size: $size}) {
              count
              rows {
                score
                target {
                  id
                  approvedSymbol
                  approvedName
                }
              }
            }
          }
        }
        """
        data = await self.graphql(q, {"diseaseId": disease_id, "size": size})
        rows = (
            data.get("disease", {})
            .get("associatedTargets", {})
            .get("rows", [])
            or []
        )
        return rows

    async def target_known_drugs(self, target_id: str, size: int = 10) -> list[dict[str, Any]]:
        q = """
        query TargetKnownDrugs($targetId: String!, $size: Int!) {
          target(ensemblId: $targetId) {
            id
            knownDrugs(size: $size) {
              uniqueDrugs
              rows {
                drugId
                drugType
                prefName
                phase
                mechanismOfAction
              }
            }
          }
        }
        """
        data = await self.graphql(q, {"targetId": target_id, "size": size})
        raw_rows = data.get("target", {}).get("knownDrugs", {}).get("rows", []) or []
        normalised = []
        for r in raw_rows:
            normalised.append({
                "drug": {"id": r.get("drugId", ""), "name": r.get("prefName", "")},
                "phase": r.get("phase"),
                "status": r.get("mechanismOfAction"),
            })
        return normalised

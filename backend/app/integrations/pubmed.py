from __future__ import annotations

from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential


NCBI_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


class PubMedClient:
    def __init__(self, http: httpx.AsyncClient):
        self.http = http

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def esearch(self, term: str, retmax: int = 5) -> list[str]:
        params = {"db": "pubmed", "term": term, "retmode": "json", "retmax": str(retmax)}
        r = await self.http.get(f"{NCBI_EUTILS}/esearch.fcgi", params=params)
        r.raise_for_status()
        data = r.json()
        return data.get("esearchresult", {}).get("idlist", []) or []

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def esummary(self, pmids: list[str]) -> dict[str, Any]:
        if not pmids:
            return {}
        params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "json"}
        r = await self.http.get(f"{NCBI_EUTILS}/esummary.fcgi", params=params)
        r.raise_for_status()
        return r.json()


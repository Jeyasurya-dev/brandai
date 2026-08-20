"""
TrademarkService
-----------------
Provider-based trademark screening architecture. This module NEVER
fabricates a result and NEVER claims "available"/"cleared"/"safe to
register" — only a real, configured provider's actual response can produce
a conclusion, and even then the wording stays to preliminary-screening
language (see TrademarkRisk).

Supported providers (set TRADEMARK_PROVIDER):
  - "none"        (default) — honest "Search Failed" state, no network call.
  - "markerapi"   — USPTO/US-only search via markerapi.com's documented
                    REST API (https://markerapi.com/documentation/). Requires
                    an active markerapi subscription: set
                    TRADEMARK_API_USERNAME / TRADEMARK_API_PASSWORD.
  - "generic_rest"— bring-your-own REST provider via TRADEMARK_API_BASE_URL
                    / TRADEMARK_API_KEY. You must adapt _search_generic_rest
                    to your provider's actual response shape before use —
                    it is a documented integration point, not a live one.

Jurisdiction handling: markerapi only covers USPTO (United States)
registrations. If the requested jurisdiction (derived from the user's
Phase 3 "target market" advanced field) isn't the US, this service reports
an honest "not applicable to this jurisdiction" result rather than running
a US search and implying it covers the requested market. There is currently
no built-in provider for India, the UK, the EU, or "Global" — those return
an honest unavailable state pointing at the right official registry until a
provider is configured for them.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
import requests
from flask import current_app

LEGAL_DISCLAIMER = (
    "Automated trademark screening is preliminary and is not legal advice. "
    "Confirm availability through the relevant official trademark registry "
    "and qualified legal counsel before adopting a brand."
)

# Official registries to point users at when we have no automated provider
# for their jurisdiction — never claim a search happened when it didn't.
OFFICIAL_REGISTRY_BY_JURISDICTION = {
    "IN": "the Indian Trade Marks Registry (ipindiaonline.gov.in)",
    "US": "USPTO TESS (tmsearch.uspto.gov)",
    "GB": "the UK IPO trademark search (gov.uk/search-for-trademark)",
    "EU": "EUIPO eSearch (euipo.europa.eu)",
    "GLOBAL": "WIPO's Global Brand Database (branddb.wipo.int)",
}


def normalize_name(name: str) -> str:
    """Lowercase, strip punctuation/whitespace differences so 'Nova Byte'
    and 'novabyte' are recognized as the same search term."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def infer_jurisdiction(advanced: Optional[dict]) -> dict:
    """Derives a screening jurisdiction from the Phase 3 advanced brief's
    'target_market' field. Never guesses a jurisdiction the user didn't
    imply — if nothing was specified, jurisdiction is explicitly 'Not
    specified' rather than silently defaulting to the US."""
    market = ((advanced or {}).get("target_market") or "").strip()
    if not market:
        return {"label": "Not specified", "code": None}

    lower = market.lower()
    keyword_map = [
        (("india", "tamil nadu", "bharat", "bengaluru", "chennai", "mumbai", "delhi"), "India", "IN"),
        (("usa", "united states", "america", "us market"), "USA", "US"),
        (("uk", "united kingdom", "britain", "england"), "UK", "GB"),
        (("eu", "europe", "european union"), "EU", "EU"),
        (("global", "worldwide", "international"), "Global", "GLOBAL"),
    ]
    for keywords, label, code in keyword_map:
        if any(k in lower for k in keywords):
            return {"label": label, "code": code}

    # User specified something we don't recognize as a known jurisdiction —
    # show exactly what they typed rather than silently discarding it.
    return {"label": market, "code": None}


@dataclass
class TrademarkResult:
    status: str  # one of TrademarkRisk values
    details: dict
    provider: str


class TrademarkService:
    def __init__(
        self,
        provider: str,
        api_key: str = "",
        base_url: str = "",
        username: str = "",
        password: str = "",
    ):
        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url
        self.username = username
        self.password = password

    @classmethod
    def from_app_config(cls):
        return cls(
            provider=current_app.config.get("TRADEMARK_PROVIDER", "none"),
            api_key=current_app.config.get("TRADEMARK_API_KEY", ""),
            base_url=current_app.config.get("TRADEMARK_API_BASE_URL", ""),
            username=current_app.config.get("TRADEMARK_API_USERNAME", ""),
            password=current_app.config.get("TRADEMARK_API_PASSWORD", ""),
        )

    def is_configured(self) -> bool:
        if self.provider == "markerapi":
            return bool(self.username and self.password)
        if self.provider == "generic_rest":
            return bool(self.api_key and self.base_url)
        return False

    def search(self, name: str, jurisdiction: Optional[dict] = None) -> TrademarkResult:
        jurisdiction = jurisdiction or {"label": "Not specified", "code": None}
        timestamp = datetime.now(timezone.utc).isoformat()
        base_details = {
            "searched_name": name,
            "normalized_name": normalize_name(name),
            "jurisdiction": jurisdiction["label"],
            "jurisdiction_code": jurisdiction["code"],
            "timestamp": timestamp,
            "disclaimer": LEGAL_DISCLAIMER,
        }

        if not self.is_configured():
            return TrademarkResult(
                status="Search Failed",
                details={
                    **base_details,
                    "reason": "No trademark data provider is configured on this server.",
                },
                provider=self.provider,
            )

        # markerapi only covers USPTO (US) registrations — be explicit when
        # the requested jurisdiction is something else rather than silently
        # running a US-only search and implying broader coverage.
        if self.provider == "markerapi" and jurisdiction["code"] not in (None, "US"):
            registry = OFFICIAL_REGISTRY_BY_JURISDICTION.get(
                jurisdiction["code"], "the relevant national trademark office"
            )
            return TrademarkResult(
                status="Needs Manual Review",
                details={
                    **base_details,
                    "reason": (
                        f"The configured provider (markerapi) only covers USPTO (United States) "
                        f"registrations and cannot screen the requested jurisdiction "
                        f"({jurisdiction['label']}). No automated result is available for this "
                        f"market yet — check {registry} directly."
                    ),
                },
                provider=self.provider,
            )

        try:
            return self._dispatch(name, jurisdiction, base_details)
        except Exception as e:
            return TrademarkResult(
                status="Search Failed",
                details={**base_details, "reason": f"Provider request error: {e}"},
                provider=self.provider,
            )

    def _dispatch(self, name: str, jurisdiction: dict, base_details: dict) -> TrademarkResult:
        if self.provider == "markerapi":
            return self._search_markerapi(name, base_details)
        if self.provider == "generic_rest":
            return self._search_generic_rest(name, base_details)
        raise NotImplementedError(f"Unknown trademark provider '{self.provider}'")

    def _search_markerapi(self, name: str, base_details: dict) -> TrademarkResult:
        """
        USPTO wordmark search via markerapi.com's documented v1 endpoint:
        https://markerapi.com/documentation/
        GET /api/v1/trademark/search/{search}/username/{username}/password/{password}
        Response: {"count": N, "trademarks": [{"serialnumber", "wordmark",
        "code", "description", "registrationdate"}, ...]}
        """
        url = (
            f"https://markerapi.com/api/v1/trademark/search/"
            f"{requests.utils.quote(name)}/username/{self.username}/password/{self.password}"
        )
        resp = requests.get(url, timeout=8)
        resp.raise_for_status()
        data = resp.json()

        trademarks = data.get("trademarks") or []
        normalized_query = normalize_name(name)

        exact_matches = []
        similar_matches = []
        classes = set()

        for tm in trademarks:
            wordmark = tm.get("wordmark", "") or ""
            entry = {
                "wordmark": wordmark,
                "serial_number": tm.get("serialnumber"),
                "class_code": tm.get("code"),
                "description": tm.get("description"),
                "registration_date": tm.get("registrationdate"),
            }
            if tm.get("code"):
                classes.add(tm["code"])
            if normalize_name(wordmark) == normalized_query:
                exact_matches.append(entry)
            else:
                similar_matches.append(entry)

        if exact_matches:
            status = "High Risk"
            explanation = (
                f"{len(exact_matches)} exact USPTO wordmark match(es) found for \"{name}\". "
                "Review these registrations before proceeding."
            )
        elif similar_matches:
            status = "Medium Risk"
            explanation = (
                f"No exact match, but {len(similar_matches)} related USPTO record(s) turned up "
                f"for \"{name}\". Review for potential conflict."
            )
        elif data.get("count", 0) == 0 and trademarks == []:
            status = "Low Risk"
            explanation = f'No obvious USPTO match found for "{name}" in this preliminary screening.'
        else:
            status = "Needs Manual Review"
            explanation = "Provider response was ambiguous — review manually."

        return TrademarkResult(
            status=status,
            details={
                **base_details,
                "provider_coverage": "USPTO (United States) wordmarks only",
                "exact_matches": exact_matches,
                "similar_matches": similar_matches,
                "phonetic_matches": None,  # markerapi does not offer phonetic search
                "classes": sorted(classes),
                "explanation": explanation,
                "raw_response": {"count": data.get("count"), "result_count": len(trademarks)},
            },
            provider=self.provider,
        )

    def _search_generic_rest(self, name: str, base_details: dict) -> TrademarkResult:
        """Integration point for a bring-your-own REST trademark provider.
        Adapt the request/response shape below to your actual provider —
        this default shape is illustrative only and must be updated before
        relying on it for real screening."""
        resp = requests.get(
            f"{self.base_url}/search",
            params={"q": name},
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()

        exact_hits = data.get("exact_matches", [])
        similar_hits = data.get("similar_matches", [])

        if exact_hits:
            status = "High Risk"
        elif similar_hits:
            status = "Medium Risk"
        elif data.get("total_results", 0) == 0:
            status = "Low Risk"
        else:
            status = "Needs Manual Review"

        return TrademarkResult(
            status=status,
            details={
                **base_details,
                "exact_matches": exact_hits,
                "similar_matches": similar_hits,
                "phonetic_matches": data.get("phonetic_matches"),
                "classes": data.get("classes", []),
                "explanation": f"{len(exact_hits)} exact / {len(similar_hits)} similar match(es) via {self.provider}.",
                "raw_response": {"total_results": data.get("total_results")},
            },
            provider=self.provider,
        )

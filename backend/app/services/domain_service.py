"""
DomainService
--------------
Provider-based domain availability checking across the TLDs the PRD
requires (.com, .in, .ai, .io, .co). Never fabricates availability — a
domain is only ever reported "available" when a real registry lookup
actually came back with no registration record.

Default provider: "rdap" — the free, public, no-API-key RDAP bootstrap
service maintained by IANA/ICANN (https://rdap.org). RDAP (RFC 7482) is the
modern, structured successor to WHOIS; querying https://rdap.org/domain/
<name> transparently routes to the domain's authoritative registry and
returns a real registration record if one exists, or a 404 if it doesn't.
No credentials are required, which is why this is the default rather than
"none" — real screening works out of the box.

Set DOMAIN_PROVIDER=none to disable outbound domain lookups entirely, or
DOMAIN_PROVIDER=generic_rest to plug in a paid provider (Namecheap, GoDaddy,
WhoisXML, etc.) via DOMAIN_API_BASE_URL / DOMAIN_API_KEY — adapt
_check_generic_rest to that provider's actual response shape first.

Caveat, shown honestly rather than silently: not every ccTLD's registry has
adopted RDAP yet, and a missing record isn't a 100% legal guarantee a
domain is purchasable (e.g. reserved names, pending transfers). We report
"unknown" rather than "available" whenever the signal is ambiguous.
"""

from typing import List, Dict
import requests
from flask import current_app

SUPPORTED_TLDS = ["com", "in", "ai", "io", "co"]

# Statuses: "available", "taken", "unknown", "search_failed"
# ("unavailable" is kept as an alias of "search_failed" for backwards
# compatibility with any code/UI still checking for it.)


class DomainService:
    def __init__(self, provider: str, api_key: str = "", base_url: str = ""):
        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url

    @classmethod
    def from_app_config(cls):
        return cls(
            provider=current_app.config.get("DOMAIN_PROVIDER", "rdap"),
            api_key=current_app.config.get("DOMAIN_API_KEY", ""),
            base_url=current_app.config.get("DOMAIN_API_BASE_URL", ""),
        )

    def is_configured(self) -> bool:
        if self.provider == "rdap":
            return True  # no credentials needed — public bootstrap service
        if self.provider == "generic_rest":
            return bool(self.api_key and self.base_url)
        return False

    def check(self, name: str, tlds: List[str] = None) -> Dict[str, str]:
        tlds = tlds or SUPPORTED_TLDS
        if not self.is_configured():
            return {tld: "search_failed" for tld in tlds}

        result = {}
        for tld in tlds:
            try:
                result[tld] = self._dispatch(name, tld)
            except Exception:
                result[tld] = "search_failed"
        return result

    def _dispatch(self, name: str, tld: str) -> str:
        if self.provider == "rdap":
            return self._check_rdap(name, tld)
        if self.provider == "generic_rest":
            return self._check_generic_rest(name, tld)
        raise NotImplementedError(f"Unknown domain provider '{self.provider}'")

    def _check_rdap(self, name: str, tld: str) -> str:
        domain = f"{name}.{tld}".lower()
        try:
            resp = requests.get(f"https://rdap.org/domain/{domain}", timeout=6)
        except requests.RequestException:
            return "search_failed"

        if resp.status_code == 200:
            # A real registration record was returned — the domain is taken.
            return "taken"
        if resp.status_code == 404:
            # The registry has no record for this name. This is a real,
            # positive signal (not a guess) — but RDAP coverage varies by
            # TLD and reserved/pending names can still 404, so we report
            # "available" only for this direct "not found" case and leave
            # anything murkier as "unknown".
            return "available"
        if resp.status_code in (400, 422):
            # Malformed/unsupported query for this TLD's registry.
            return "unknown"
        # Rate limited, registry down, referral loop, etc.
        return "unknown"

    def _check_generic_rest(self, name: str, tld: str) -> str:
        """Integration point for a bring-your-own REST domain provider.
        Adapt the request/response shape below to your actual provider —
        this default shape is illustrative only and must be updated before
        relying on it for real screening."""
        domain = f"{name}.{tld}"
        resp = requests.get(
            f"{self.base_url}/availability",
            params={"domain": domain},
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=6,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("available") is True:
            return "available"
        if data.get("available") is False:
            return "taken"
        return "unknown"

"""Isolated external providers for polymer notation and public lookups.

Providers return research candidates with request/response provenance. Network
lookups are opt-in per call and never mutate the registry or catalog.
"""
from __future__ import annotations
import hashlib, json, re
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class BigSMILESProvider:
    """Small, conservative BigSMILES/BigSMARTS contract.

    This intentionally validates and indexes notation without translating a
    stochastic polymer into a finite molecule. Full grammar coverage remains a
    separate research task.
    """
    version = "bigsmiles-contract-0.1"

    def parse(self, notation: str) -> dict:
        if not isinstance(notation, str) or not notation.strip() or len(notation) > 20000:
            return {"status": "INVALID", "reason_code": "BIGSMILES_INPUT_INVALID"}
        text = notation.strip()
        braces = text.count("{") == text.count("}") and text.count("{") > 0
        linear_ports = text.count("[*]") >= 2
        bracket_ok = text.count("[") == text.count("]")
        if (not braces and not linear_ports) or not bracket_ok:
            return {"status": "NEEDS_DETAILS", "reason_code": "BIGSMILES_SYNTAX_OUT_OF_SCOPE",
                    "notation": text, "provider": self.version}
        stochastic = re.findall(r"\{([^{}]*)\}", text)
        alternatives=[]
        for obj in stochastic:
            alternatives.extend([x.strip() for x in obj.split(',') if x.strip()])
        labels = sorted(set(re.findall(r"(?:<|>)[A-Za-z0-9]+", text)))
        bonding_descriptors = sorted(set(re.findall(r"\[(?:<|>)[^\]]*\]", text)))
        objects = re.findall(r"\[[^\[\]]+\]", text)
        return {"status": "PARSED", "notation": text, "provider": self.version,
                "candidate_class": "POLYMER_OBJECT_NOT_FINITE_GRAPH",
                "stochastic_objects": stochastic, "stochastic_alternatives": alternatives,
                "connection_labels": labels, "bonding_descriptors": bonding_descriptors,
                "bracket_atom_tokens": objects, "evidence_status": "COMPUTED_NOT_REVIEWED",
                "independent_review": "PENDING"}

    def match(self, notation: str, pattern: str) -> dict:
        parsed = self.parse(notation)
        if parsed.get("status") != "PARSED":
            return {**parsed, "match": "INCONCLUSIVE"}
        if not isinstance(pattern, str) or not pattern.strip():
            return {"status": "INVALID", "reason_code": "BIGSMARTS_PATTERN_REQUIRED"}
        # Contract-level lexical match; a SMARTS graph engine is future work.
        return {"status": "PARSED", "match": pattern in notation,
                "match_scope": "BIGSMARTS_LEXICAL_CONTRACT",
                "notation": notation, "pattern": pattern,
                "provider": self.version, "independent_review": "PENDING"}


class PubChemCactusProvider:
    """Public resolver with opt-in network and bounded request metadata."""
    version = "pubchem-cactus-provider-0.1"

    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout

    def _get(self, url: str, allow_network: bool) -> dict:
        if not allow_network:
            return {"status": "NEEDS_DETAILS", "reason_code": "NETWORK_NOT_AUTHORIZED",
                    "url": url, "provider": self.version}
        req = Request(url, headers={"User-Agent": "PolymerIdentityResearch/0.1"})
        try:
            with urlopen(req, timeout=self.timeout) as response:
                body = response.read(2_000_000)
                return {"status": "PARSED", "http_status": response.status,
                        "response_sha256": _sha(body), "body": body}
        except HTTPError as exc:
            reason = "PUBLIC_LOOKUP_NO_MATCH" if exc.code == 404 else "PUBLIC_LOOKUP_HTTP_ERROR"
            return {"status": "NEEDS_DETAILS", "reason_code": reason,
                    "http_status": exc.code, "detail": str(exc)}
        except (URLError, TimeoutError, OSError) as exc:
            return {"status": "NEEDS_DETAILS", "reason_code": "PUBLIC_LOOKUP_UNAVAILABLE",
                    "detail": str(exc)}

    def _pubchem_structure(self, input_kind: str, value: str, *, allow_network: bool = False) -> dict:
        if input_kind not in {"name", "smiles", "inchi"}:
            return {"status": "INVALID", "reason_code": "PUBLIC_LOOKUP_INPUT_KIND_INVALID"}
        if not isinstance(value, str) or not value.strip() or len(value) > 500:
            return {"status": "INVALID", "reason_code": "PUBLIC_LOOKUP_NAME_INVALID"}
        url = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/" + input_kind + "/" + quote(value.strip(), safe="") + "/property/IUPACName,MolecularFormula,MolecularWeight,CanonicalSMILES,IsomericSMILES,InChI,InChIKey/JSON"
        result = self._get(url, allow_network)
        out = {k: v for k, v in result.items() if k != "body"}
        out.update({"provider": "PubChem", "query": value, "query_kind": input_kind, "url": url,
                    "candidate_class": "FINITE_SOURCE_MOLECULE", "independent_review": "PENDING"})
        if result.get("status") == "PARSED":
            try:
                payload = json.loads(result["body"])
                props = payload.get("PropertyTable", {}).get("Properties", [])
                out["candidates"] = props
                out["status"] = "PARSED" if len(props) == 1 else ("AMBIGUOUS" if props else "NEEDS_DETAILS")
                if not props: out["reason_code"] = "PUBLIC_LOOKUP_NO_MATCH"
            except (ValueError, TypeError):
                out.update({"status": "NEEDS_DETAILS", "reason_code": "PUBLIC_LOOKUP_INVALID_JSON"})
        return out

    def pubchem_name(self, name: str, *, allow_network: bool = False) -> dict:
        return self._pubchem_structure("name", name, allow_network=allow_network)

    def pubchem_smiles(self, smiles: str, *, allow_network: bool = False) -> dict:
        return self._pubchem_structure("smiles", smiles, allow_network=allow_network)

    def cactus_name(self, name: str, *, allow_network: bool = False) -> dict:
        return self.cactus_representation(name, "smiles", allow_network=allow_network, query_kind="name")

    def cactus_representation(self, identifier: str, representation: str, *, allow_network: bool = False,
                              query_kind: str = "structure") -> dict:
        if representation not in {"smiles", "stdinchi", "stdinchikey", "names"}:
            return {"status": "INVALID", "reason_code": "CACTUS_REPRESENTATION_INVALID"}
        if not isinstance(identifier, str) or not identifier.strip() or len(identifier) > 500:
            return {"status": "INVALID", "reason_code": "PUBLIC_LOOKUP_NAME_INVALID"}
        url = "https://cactus.nci.nih.gov/chemical/structure/" + quote(identifier.strip(), safe="") + "/" + representation
        result = self._get(url, allow_network)
        out = {k: v for k, v in result.items() if k != "body"}
        out.update({"provider": "Cactus", "query": identifier, "query_kind": query_kind, "url": url,
                    "candidate_class": "FINITE_SOURCE_MOLECULE", "independent_review": "PENDING"})
        if result.get("status") == "PARSED":
            value = result["body"].decode("utf-8", errors="replace").strip()
            out[representation] = value
            if not value:
                out.update({"status": "NEEDS_DETAILS", "reason_code": "PUBLIC_LOOKUP_NO_MATCH"})
        return out

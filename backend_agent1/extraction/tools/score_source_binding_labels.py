"""Score a small source-reviewed material-binding set, without GT value matching."""
import hashlib
import json
from pathlib import Path


def load_labels(path):
    path = Path(path).resolve()
    snapshots = {path: path.read_bytes()}
    data = json.loads(snapshots[path])
    if data.get("schema_version") != "source_binding_labels.v1":
        raise ValueError("Unsupported source labels")
    for source, expected in data["source_hashes"].items():
        p = Path(source).resolve()
        content = p.read_bytes()
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError("Reviewed identity source changed")
        snapshots[p] = content
    labels = data["labels"]
    if len({(r["document_id"], r["source_cell_id"]) for r in labels}) != len(labels):
        raise ValueError("Duplicate reviewed cell")
    if any(not r.get("reviewer") or not r.get("review_basis") or not r.get("expected_entity_id")
           or "expected_sample_id" not in r or (r["expected_sample_id"] is None and not r.get("forbidden_sample_ids")) for r in labels):
        raise ValueError("Independent source review is required")
    return labels, snapshots


def score(labels, publications):
    rows = []
    for label in labels:
        publication = publications.get(label["document_id"]) or {}
        claims = []
        for status in ("final", "candidate", "not_publishable"):
            for group in publication.get(status, []):
                identity = group["identity"]
                if identity.get("source_cell_ids") != [label["source_cell_id"]]:
                    continue
                record = group.get("record") or {}
                if identity.get("sample_id"):
                    if label["expected_sample_id"] is None:
                        correct = False if (identity["sample_id"] in label.get("forbidden_sample_ids", [])
                                            or identity.get("entity_id") not in (None, label["expected_entity_id"])) else None
                    else:
                        correct = identity["sample_id"] == label["expected_sample_id"] and identity.get("entity_id") in (None, label["expected_entity_id"])
                elif record.get("binding_status") == "article_alias_confirmed":
                    correct = record.get("article_sample_label_raw") == label["expected_article_alias"] and label["sample_axis_cell_id"] in record.get("binding_evidence_ids", [])
                elif identity.get("entity_id"):
                    correct = identity["entity_id"] == label["expected_entity_id"]
                else:
                    correct = None
                claims.append({"measurement_id": group["measurement_id"], "publication_status": status, "correct_binding": correct})
        rows.append({"document_id": label["document_id"], "source_cell_id": label["source_cell_id"], "claims": claims,
                     "covered": bool(claims), "all_bindings_correct": bool(claims) and all(c["correct_binding"] is True for c in claims)})
    covered = sum(r["covered"] for r in rows)
    correct = sum(r["all_bindings_correct"] for r in rows)
    wrong = sum(c["correct_binding"] is False for r in rows for c in r["claims"])
    accepted_wrong = sum(c["publication_status"] == "final" and c["correct_binding"] is False for r in rows for c in r["claims"])
    return {"scope": "source-reviewed development diagnostic material-binding subset, not population sample accuracy",
            "labelled_cells": len(rows), "covered_cells": covered, "correct_binding_cells": correct,
            "binding_accuracy_on_covered_cells": correct / covered if covered else None,
            "unresolved_binding_claims": sum(c["correct_binding"] is None for r in rows for c in r["claims"]),
            "incorrect_binding_claims": wrong, "incorrect_binding_claims_published": accepted_wrong,
            "false_acceptance_on_incorrect_claims": accepted_wrong / wrong if wrong else None, "rows": rows}

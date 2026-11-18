"""Stable, read-only projection of a material's identity and naming scope.

The solver keeps source identity, graph candidates and naming claims separate.
This module gives the reader and post-seal review one compact view without
promoting a local graph or a source-only descriptor to a whole repeat unit.
"""

from __future__ import annotations

from copy import deepcopy


def _items(value):
    if value in (None, "", [], {}):
        return []
    return value if isinstance(value, list) else [value]


def _text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return str(value.get("text") or value.get("name") or "").strip()
    return str(value).strip()


def _unique(values):
    out = []
    seen = set()
    for value in values:
        key = _text(value)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(deepcopy(value))
    return out


def whole_repeat_valid(material: dict, graphs: dict | None = None) -> bool:
    """Return true only for an explicitly bound two-port ideal repeat graph."""
    graphs = graphs or {}
    expression = material.get("structure_expression") or {}
    constitution = material.get("constitution") or {}
    gids = expression.get("graph_ids") or []
    if expression.get("kind") != "ideal_repeat" or len(gids) != 1:
        return False
    gid = gids[0]
    graph = graphs.get(gid) or {}
    return bool(
        graph.get("scope") == "repeat_unit"
        and len(graph.get("ports") or []) == 2
        and constitution.get("graph_id") == gid
        and constitution.get("coverage") == "ideal_repeat"
        and gid in (material.get("graph_ids") or [])
    )


def _source_names(material: dict, assessment: dict) -> list[str]:
    values = [
        material.get("label"),
        material.get("passport_name"),
        material.get("source_name"),
        *_items(material.get("source_names")),
        *_items(material.get("source_aliases")),
        *_items(material.get("aliases")),
    ]
    alternative = assessment.get("source_alternative") if isinstance(assessment, dict) else None
    if isinstance(alternative, dict):
        values.append(alternative.get("text"))
    return [str(x) for x in _unique(values)]


def package(material: dict, graphs: dict | None = None) -> dict:
    """Build the compact identity package used by the reader/evaluation UI."""
    graphs = graphs or {}
    name = material.get("most_likely_name") or {}
    if not isinstance(name, dict):
        name = {"text": name}
    expression = material.get("structure_expression") or {}
    assessment = material.get("iupac_assessment") or {}
    declaration = material.get("nomenclature_declaration") or {}

    graph_rows = []
    for gid in material.get("graph_ids") or []:
        graph = graphs.get(gid) or {}
        graph_rows.append({
            "id": gid,
            "scope": graph.get("scope"),
            "formula": graph.get("repeat_formula") or graph.get("formula"),
            "ports": len(graph.get("ports") or []),
        })

    unknowns = _unique([
        *(_items(material.get("unknowns"))),
        *(_items(name.get("unknowns"))),
        *(_items(expression.get("unknowns"))),
        *(_items(assessment.get("remaining"))),
    ])
    qualifiers = _unique([
        *(_items(name.get("identity_qualifiers"))),
        *(_items(assessment.get("identity_qualifiers"))),
        *(_items(declaration.get("identity_qualifiers"))),
        *(_items(expression.get("identity_qualifiers"))),
    ])
    whole = whole_repeat_valid(material, graphs)
    kind = expression.get("kind") or ("ideal_repeat" if whole else None)
    if kind in ("local_connectivity", "source_only"):
        scope_note = "局部/来源范围；不代表完整理想重复单元"
    elif kind == "assembly":
        scope_note = "组装/物理配方范围；不代表共价整体重复单元"
    elif whole:
        scope_note = "明确绑定的理想重复单元"
    else:
        scope_note = "以已保存图和来源声明为准"
    named_unknowns = _items(name.get("unknowns"))
    return {
        "source_names": _source_names(material, assessment),
        "candidate_name": name.get("text"),
        "candidate_basis": name.get("basis"),
        "candidate_scope": name.get("scope"),
        "structure_kind": kind,
        "structure_evidence_basis": expression.get("evidence_basis"),
        "scope_note": scope_note,
        "whole_repeat_valid": whole,
        "graphs": graph_rows,
        "identity_qualifiers": qualifiers,
        "unknowns": unknowns,
        "unknowns_propagated_to_name": bool(not unknowns or set(map(_text, unknowns)).issubset(set(map(_text, named_unknowns))))
    }

# -*- coding: utf-8 -*-
"""Preview 与 PolyInfo 审计行的对象级组合匹配器。

该模块只服务于审计/评估，不修改 Preview 的最终 JSON。与旧的平面字符串
匹配不同，这里保留对象之间的 evidence/table/sample/property 等锚点，允许
名称、值、方法和条件分布在不同对象时进行可解释的组合判断。
"""

from __future__ import annotations

import re
import json
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Iterable, Mapping


NUMBER_RE = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?", re.I)
TAG_RE = re.compile(r"<[^>]+>")
SAMPLE_ID_RE = re.compile(r"\b[a-z]{1,12}[-_]?\d+(?:/\d+)?(?:\s*[a-z]{1,6})?\b", re.I)

STOP_WORDS = {
    "property", "properties", "value", "values", "item", "items", "field",
    "information", "characteristics", "material", "sample", "polymer", "source",
    "method", "measurement", "condition", "conditions", "status", "general", "type",
    "data", "record", "recorded", "raw", "normalised", "normalized", "the", "and",
    "with", "for", "from", "of", "at", "in", "to", "by", "as", "on", "vs", "except",
    "unit", "units", "名称", "性质", "数据", "字段", "方法", "条件", "测量", "样品", "材料",
    "信息", "记录",
}

# 词表按语义族组织，匹配器只输出 canonical token，不写文献编号特例。
NAME_ALIAS_GROUPS = {
    "pvc": {"pvc", "poly vinyl chloride", "polyvinyl chloride"},
    "coc": {"coc", "cyclic olefin copolymer"},
    "pcl": {"pcl", "poly epsilon caprolactone", "poly e caprolactone"},
    "pdlla": {"pdlla", "poly dl lactide", "poly dl lactic acid"},
    "plga": {"plga", "plg", "poly lactide glycolide", "poly dl lactide co glycolide"},
    "nbr": {"nbr", "acrylonitrile butadiene rubber", "nitrile rubber"},
    "peo": {"peo", "polyethylene oxide"},
    "xrd": {"xrd", "x ray diffraction", "x ray powder diffraction", "wide angle x ray diffraction"},
    "dsc": {"dsc", "differential scanning calorimetry"},
    "tga": {"tga", "thermogravimetric analysis", "thermal gravimetric analysis"},
    "gpc": {"gpc", "gel permeation chromatography"},
    "nmr": {"nmr", "nuclear magnetic resonance"},
    "uv_vis": {"uv vis", "uv vis spectroscopy", "ultraviolet visible"},
    "glass_transition": {"glass transition", "glass transition temperature", "tg"},
    "melting_temperature": {"melting", "melting temperature", "melting point", "tm"},
    "crystallinity": {"crystallinity", "crystalline", "degree of crystallinity", "crystal"},
    "molecular_weight": {"molecular weight", "molar mass", "average molar mass", "mn", "mw", "pdi"},
    "viscosity": {
        "viscosity", "viscosities", "intrinsic viscosity", "intrinsic viscosities",
        "inherent viscosity", "inherent viscosities", "reduced viscosity",
    },
    "conductivity": {"conductivity", "electric conductivity", "ionic conductivity", "resistivity"},
    "surface_energy": {"surface energy", "surface tension"},
    "contact_angle": {"contact angle", "water contact angle"},
    "tensile": {"tensile", "tensile strength", "tensile modulus", "young s modulus", "elongation"},
    "solubility": {"solubility", "solvent", "non solvent"},
    "processing": {"processing", "processing information", "molding", "moulding", "casting", "film"},
    "polymerization": {"polymerization", "polymerisation", "reactant", "initiator"},
    "additive": {"additive", "additives", "doping", "filler", "salt"},
    "material_type": {"material type", "polymer class", "shape", "morphology"},
}

METHOD_CANONICAL = {
    "xrd": {"xrd", "x ray diffraction", "x ray powder diffraction", "wide angle x ray diffraction"},
    "dsc": {"dsc", "differential scanning calorimetry"},
    "tga": {"tga", "thermogravimetric analysis", "thermal gravimetric analysis"},
    "gpc": {"gpc", "gel permeation chromatography"},
    "nmr": {"nmr", "nuclear magnetic resonance"},
    "uv_vis": {"uv vis", "uv vis spectroscopy", "ultraviolet visible"},
    "igc": {"igc", "inverse gas chromatography"},
    "dma": {"dma", "dynamic mechanical analysis"},
    "ftir": {"ftir", "fourier transform infrared", "infrared spectroscopy"},
    "sem": {"sem", "scanning electron microscopy"},
    "tem": {"tem", "transmission electron microscopy"},
}

COLLECTION_KIND = {
    "material_mentions": "name",
    "polymer_entities": "name",
    "samples": "sample",
    "process_steps": "process",
    "measurement_conditions": "condition",
    "property_observations": "value",
    "unresolved_property_observations": "value",
    "property_series": "value",
    "property_series.points": "value",
    "characterizations": "method",
    "specialized_property_observations": "value",
    "evidence": "evidence",
}

NAME_KEYS = {
    "text", "name", "polymer_name", "polymer_type", "material_type", "sample_label_raw",
    "state_description", "source_names", "process_type", "property_name_raw",
    "property_name_normalized", "semantic_label", "source_field", "property_title",
    "property_category", "value_kind", "method_raw", "method_normalized",
}
VALUE_KEYS = {
    "value_raw", "value_min", "value_max", "categorical_value", "text_value",
    "result_summary", "cell_value", "property_value", "property_value_min", "property_value_max",
}
METHOD_KEYS = {
    "method_raw", "method_normalized", "determination_method_raw", "measurement_method",
    "instrument", "method", "measurement_method_raw",
}
CONDITION_KEYS = {
    "measurement_context", "conditions", "parameters", "temperature", "frequency",
    "humidity", "pressure", "wavelength", "solvent", "atmosphere", "gas_flow",
    "heating_rate", "time", "duration", "concentration", "composition", "unit_raw",
}
ANCHOR_KEYS = {
    "sample_id": "sample_id",
    "sample_ids": "sample_id",
    "input_sample_ids": "sample_id",
    "output_sample_ids": "sample_id",
    "entity_id": "entity_id",
    "entity_ids": "entity_id",
    "refers_to_entity": "entity_id",
    "series_id": "series_id",
    "series_ids": "series_id",
    "property_id": "property_id",
    "property_ids": "property_id",
    "derived_property_ids": "property_id",
    "characterization_id": "characterization_id",
    "measurement_condition_id": "measurement_condition_id",
    "evidence_id": "evidence_id",
    "evidence_ids": "evidence_id",
    "block_id": "block_id",
    "source_block_ids": "block_id",
    "table_id": "table_id",
    "cell_id": "cell_id",
}
STRONG_ANCHORS = {
    "evidence_id", "cell_id", "property_id", "series_id", "characterization_id",
    "measurement_condition_id", "sample_id", "entity_id",
}
MEDIUM_ANCHORS = {"block_id", "table_id", "table_row", "table_label", "sample_label"}


def norm_text(value: Any) -> str:
    text = TAG_RE.sub(" ", str(value or ""))
    text = unicodedata.normalize("NFKC", text).casefold()
    text = text.replace("−", "-").replace("–", "-").replace("—", "-")
    text = re.sub(r"\\(?:mathrm|text|mathit|mathbf|rm)\s*", "", text)
    text = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


@lru_cache(maxsize=100_000)
def _norm_text_cached(value: str) -> str:
    return norm_text(value)


@lru_cache(maxsize=100_000)
def tokens(value: str) -> frozenset[str]:
    return {
        token for token in _norm_text_cached(value).split()
        if token not in STOP_WORDS and len(token) >= 2 and not token.isdigit()
    }


@lru_cache(maxsize=100_000)
def _numbers_cached(text: str) -> tuple[float, ...]:
    result: list[float] = []
    for raw in NUMBER_RE.findall(text):
        try:
            number = float(raw)
        except ValueError:
            continue
        if abs(number) < 1e9:
            result.append(number)
    return tuple(result)


def numbers(value: Any) -> list[float]:
    text = TAG_RE.sub(" ", str(value or ""))
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("−", "-").replace("–", "-").replace("—", "-")
    text = re.sub(r"\\(?:mathrm|text|mathit|mathbf|rm)\s*", "", text)
    return list(_numbers_cached(text))


def _flatten_scalars(value: Any) -> list[str]:
    if value is None or isinstance(value, bool):
        return []
    if isinstance(value, Mapping):
        result: list[str] = []
        for child in value.values():
            result.extend(_flatten_scalars(child))
        return result
    if isinstance(value, (list, tuple, set)):
        result: list[str] = []
        for child in value:
            result.extend(_flatten_scalars(child))
        return result
    return [str(value)]


def _canonical_terms(value: Any, groups: Mapping[str, set[str]] = NAME_ALIAS_GROUPS) -> set[str]:
    text = _norm_text_cached(str(value or ""))
    if groups is NAME_ALIAS_GROUPS:
        return set(_canonical_terms_cached(text))
    result = set(tokens(text))
    for canonical, variants in groups.items():
        if any(_norm_text_cached(variant) in text for variant in variants):
            result.add(canonical)
    return result


@lru_cache(maxsize=100_000)
def _canonical_terms_cached(text: str) -> frozenset[str]:
    result = set(tokens(text))
    for canonical, variants in NAME_ALIAS_GROUPS.items():
        if any(_norm_text_cached(variant) in text for variant in variants):
            result.add(canonical)
    return frozenset(result)


def _canonical_methods(value: Any) -> set[str]:
    text = _norm_text_cached(str(value or ""))
    return set(_canonical_methods_cached(text))


@lru_cache(maxsize=100_000)
def _canonical_methods_cached(text: str) -> frozenset[str]:
    result: set[str] = set()
    for canonical, variants in METHOD_CANONICAL.items():
        if any(_norm_text_cached(variant) in text for variant in variants):
            result.add(canonical)
    return frozenset(result)


def _add_anchor(anchors: dict[str, set[str]], kind: str, value: Any) -> None:
    for item in _flatten_scalars(value):
        cleaned = norm_text(item)
        if cleaned:
            anchors.setdefault(kind, set()).add(cleaned)


def _collect_evidence(value: Any, node: "CandidateNode") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            if key_text in {"source_sentence", "caption", "text", "cell_value", "row_label", "column_label"}:
                node.evidence_texts.extend(_flatten_scalars(child))
            if key_text == "table_locator" and isinstance(child, Mapping):
                table_id = child.get("table_id")
                row_index = child.get("row_index")
                row_label = child.get("row_label")
                if table_id is not None:
                    _add_anchor(node.anchors, "table_id", table_id)
                if table_id is not None and row_index is not None:
                    _add_anchor(node.anchors, "table_row", f"{table_id}:r{row_index}")
                if table_id is not None and row_label is not None:
                    _add_anchor(node.anchors, "table_label", f"{table_id}:{row_label}")
                for locator_key in ("cell_id", "block_id"):
                    if locator_key in child:
                        _add_anchor(node.anchors, locator_key, child[locator_key])
            if key_text in ANCHOR_KEYS:
                _add_anchor(node.anchors, ANCHOR_KEYS[key_text], child)
            _collect_evidence(child, node)
    elif isinstance(value, list):
        for child in value:
            _collect_evidence(child, node)


@dataclass
class CandidateNode:
    node_id: str
    collection: str
    index: int | None
    kind: str
    name_values: list[str] = field(default_factory=list)
    value_values: list[str] = field(default_factory=list)
    method_values: list[str] = field(default_factory=list)
    condition_values: list[str] = field(default_factory=list)
    unit_values: list[str] = field(default_factory=list)
    evidence_texts: list[str] = field(default_factory=list)
    anchors: dict[str, set[str]] = field(default_factory=dict)
    evidence_only: bool = False
    _cache: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def name_text(self) -> str:
        return self.cached("name_text", lambda: " ".join(self.name_values))

    @property
    def value_text(self) -> str:
        return self.cached("value_text", lambda: " ".join(self.value_values))

    @property
    def method_text(self) -> str:
        return self.cached("method_text", lambda: " ".join(self.method_values + self.evidence_texts))

    @property
    def condition_text(self) -> str:
        return self.cached("condition_text", lambda: " ".join(self.condition_values))

    def ref(self) -> dict[str, Any]:
        return {"collection": self.collection, "index": self.index, "node_id": self.node_id}

    def cached(self, key: str, factory: Any) -> Any:
        if key not in self._cache:
            self._cache[key] = factory()
        return self._cache[key]


@dataclass
class CandidateIndex:
    nodes: list[CandidateNode]
    anchor_index: dict[tuple[str, str], list[CandidateNode]]
    _related_cache: dict[str, list[CandidateNode]] = field(default_factory=dict, repr=False)

    def related(self, node: CandidateNode) -> list[CandidateNode]:
        cached = self._related_cache.get(node.node_id)
        if cached is not None:
            return cached
        seen: set[str] = set()
        result: list[CandidateNode] = []
        for kind, values in node.anchors.items():
            for value in values:
                for other in self.anchor_index.get((kind, value), []):
                    if other.node_id not in seen:
                        seen.add(other.node_id)
                        result.append(other)
        self._related_cache[node.node_id] = result
        return result


def _new_node(collection: str, index: int | None, payload: Any, node_id: str) -> CandidateNode:
    node = CandidateNode(
        node_id=node_id,
        collection=collection,
        index=index,
        kind=COLLECTION_KIND.get(collection, "other"),
    )

    def walk(value: Any, key: str | None = None) -> None:
        if isinstance(value, Mapping):
            for child_key, child in value.items():
                child_key = str(child_key)
                if child_key in NAME_KEYS:
                    node.name_values.extend(_flatten_scalars(child))
                if child_key in VALUE_KEYS:
                    node.value_values.extend(_flatten_scalars(child))
                if child_key in METHOD_KEYS:
                    node.method_values.extend(_flatten_scalars(child))
                if child_key in CONDITION_KEYS:
                    node.condition_values.extend(_flatten_scalars(child))
                    if child_key == "parameters":
                        node.value_values.extend(_flatten_scalars(child))
                if child_key == "unit_raw":
                    node.unit_values.extend(_flatten_scalars(child))
                if child_key in ANCHOR_KEYS:
                    _add_anchor(node.anchors, ANCHOR_KEYS[child_key], child)
                if child_key in {"evidence", "evidences"}:
                    _collect_evidence(child, node)
                walk(child, child_key)
        elif isinstance(value, list):
            for child in value:
                walk(child, key)

    if collection == "evidence":
        _collect_evidence(payload, node)
    walk(payload)
    if collection == "samples":
        for value in node.name_values:
            _add_anchor(node.anchors, "sample_label", value)
    # 对身份对象，名称本身就是审计行的语义值（例如 PVC、MET-2/20 MB）。
    # 仅在没有显式 value 字段时回填，避免把属性名重复当作测量值。
    if not node.value_values and node.kind == "name":
        node.value_values.extend(node.name_values)
    return node


def build_candidate_index(final: Mapping[str, Any]) -> CandidateIndex:
    """Build object nodes and internal relation indexes from one final.json."""
    nodes: list[CandidateNode] = []
    collections = (
        "material_mentions", "polymer_entities", "samples", "process_steps",
        "measurement_conditions", "property_observations", "unresolved_property_observations",
        "property_series", "characterizations", "specialized_property_observations",
    )
    for collection in collections:
        for index, payload in enumerate(final.get(collection) or []):
            node = _new_node(collection, index, payload, f"{collection}[{index}]")
            nodes.append(node)
            if collection == "property_series":
                for point_index, point in enumerate(payload.get("points") or []):
                    point_node = _new_node(
                        "property_series.points", point_index, point,
                        f"{collection}[{index}].points[{point_index}]",
                    )
                    # Series-level property/sample/entity/condition anchors and name apply to points.
                    point_node.name_values = list(node.name_values) + point_node.name_values
                    point_node.condition_values = list(node.condition_values) + point_node.condition_values
                    point_node.unit_values = list(node.unit_values) + point_node.unit_values
                    for kind, values in node.anchors.items():
                        point_node.anchors.setdefault(kind, set()).update(values)
                    point_node.anchors.setdefault("series_id", set()).add(norm_text(payload.get("series_id")))
                    point_node._cache.clear()
                    nodes.append(point_node)

    for index, payload in enumerate(final.get("evidence") or []):
        node = _new_node("evidence", index, payload, f"evidence[{index}]")
        node.evidence_only = True
        node.value_values.extend(node.evidence_texts)
        nodes.append(node)

    anchor_index: dict[tuple[str, str], list[CandidateNode]] = {}
    for node in nodes:
        for kind, values in node.anchors.items():
            for value in values:
                if value:
                    anchor_index.setdefault((kind, value), []).append(node)
    return CandidateIndex(nodes=nodes, anchor_index=anchor_index)


@dataclass(frozen=True)
class AuditDescriptor:
    name_text: str
    sample_text: str
    value_text: str
    semantic_text: str
    primary_numbers: tuple[float, ...]
    method_text: str
    condition_text: str
    expected_name_collections: frozenset[str]
    expected_value_collections: frozenset[str]


def _primary_numbers(row: Mapping[str, Any]) -> tuple[float, ...]:
    """Extract reported value fields while excluding nested condition metadata."""
    raw = str(row.get("polyinfo_value") or "")
    field = _norm_text_cached(str(row.get("polyinfo_field") or ""))
    if re.search(r"(?:solvent|non solvent|_name|\bname\b|^method\b|_method\b|standard)", field):
        return ()
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        payload = None
    collected: list[float] = []

    def walk(value: Any, key: str = "") -> None:
        if isinstance(value, Mapping):
            for child_key, child in value.items():
                child_key = str(child_key).casefold()
                if "condition" in child_key or "method" in child_key or "unit" in child_key:
                    continue
                if (
                    child_key in {"value", "value_raw", "property_value", "categorical_value"}
                    or "value" in child_key
                    or child_key.endswith("_min")
                    or child_key.endswith("_max")
                ):
                    collected.extend(numbers(child))
                elif isinstance(child, (Mapping, list)):
                    walk(child, child_key)
        elif isinstance(value, list):
            for child in value:
                walk(child, key)

    if payload is not None:
        walk(payload)
    if not collected:
        raw_numbers = numbers(raw) or numbers(row.get("paper_value") or "")
        # 结构化标量字段（如 oxygen_index=26, standard=ASTM D2863-77）
        # 的第一个数字是主值，后续数字属于标准编号等元数据。
        collected = raw_numbers[:1] if payload is not None else raw_numbers
    # Preserve declaration order but remove repeated serialization copies.
    return tuple(dict.fromkeys(collected))


def describe_audit_row(row: Mapping[str, Any]) -> AuditDescriptor:
    field = str(row.get("polyinfo_field") or "")
    domain = str(row.get("audit_domain") or "")
    name_text = " ".join(
        str(row.get(key) or "")
        for key in ("audit_domain", "polyinfo_field", "paper_sample", "polymer_id", "sample_id")
    )
    sample_text = str(row.get("paper_sample") or "")
    value_text = " ".join(str(row.get(key) or "") for key in ("polyinfo_value", "paper_value"))
    semantic_text = f"{domain} {field}"
    # 只有审计值中明确出现方法/条件信号时，才把它们作为必需组件；
    # 不能把性质主值本身（例如 ``1.0 S/cm``）误当成测量条件。
    method_text = value_text if _canonical_methods(value_text) else ""
    condition_markers = re.compile(
        r"(?:\b(?:rh|min(?:ute)?s?|hour|day|\bn2\b|\bar\b|at\b|"
        r"solvent|atmosphere|heating\s*rate|pressure|temperature|humidity)\b|溶剂|温度|压力|湿度|气氛|升温速率)",
        re.I,
    )
    condition_text = value_text if condition_markers.search(value_text) else ""
    expected: set[str] = set()
    value_expected: set[str] = set()
    blob = norm_text(f"{domain} {field}")
    if any(term in blob for term in (
        "polymer", "material", "identity", "component", "sample",
        "聚合物", "材料", "身份", "样品", "组分", "共混",
    )):
        expected.update({"material_mentions", "polymer_entities", "samples"})
        value_expected.update({"material_mentions", "polymer_entities", "samples"})
    if any(term in blob for term in (
        "processing", "polymerization", "reactant", "post treatment", "molding", "casting",
        "加工", "成膜", "聚合工艺", "反应物", "后处理",
    )):
        expected.update({"process_steps", "samples"})
        value_expected.update({"process_steps", "samples"})
    if any(term in blob for term in (
        "method", "measurement", "characterization", "spectr", "性质", "测量", "表征",
        "conductivity", "resistivity", "tensile", "thermal", "crystallinity",
    )):
        expected.update({"characterizations", "property_observations", "specialized_property_observations"})
        value_expected.update({
            "property_observations", "unresolved_property_observations", "property_series",
            "property_series.points", "specialized_property_observations", "characterizations",
        })
    if not expected:
        expected.update({
            "property_observations", "unresolved_property_observations", "property_series",
            "property_series.points", "specialized_property_observations", "characterizations",
        })
    if not value_expected:
        value_expected.update({
            "property_observations", "unresolved_property_observations", "property_series",
            "property_series.points", "specialized_property_observations", "characterizations",
        })
    return AuditDescriptor(
        name_text=name_text,
        sample_text=sample_text,
        value_text=value_text,
        semantic_text=semantic_text,
        primary_numbers=_primary_numbers(row),
        method_text=method_text,
        condition_text=condition_text,
        expected_name_collections=frozenset(expected),
        expected_value_collections=frozenset(value_expected),
    )


def _name_score(reference: str, node: CandidateNode) -> float:
    if not reference or not node.name_text:
        return 0.0
    ref_terms = _canonical_terms(reference)
    node_terms = node.cached("name_terms", lambda: _canonical_terms(node.name_text))
    if not ref_terms or not node_terms:
        return 0.0
    overlap = ref_terms & node_terms
    if not overlap:
        return 0.0
    # A canonical alias (PVC/XRD/COC/...) is stronger than a generic token overlap.
    canonical_overlap = {
        key for key in NAME_ALIAS_GROUPS
        if key in ref_terms and key in node_terms
    }
    if canonical_overlap:
        return 0.95
    return min(0.9, 0.5 + 0.5 * len(overlap) / max(1, len(ref_terms)))


def _sample_compatible(reference: str, node: CandidateNode) -> bool:
    """Prefer exact sample labels while retaining semantic fallback for free text."""
    if not reference:
        return True
    reference_ids = {
        _norm_text_cached(item).replace(" ", "")
        for item in SAMPLE_ID_RE.findall(reference)
    }
    node_ids = {
        _norm_text_cached(item).replace(" ", "")
        for item in SAMPLE_ID_RE.findall(node.name_text)
    }
    if reference_ids and node_ids:
        return bool(reference_ids & node_ids)
    return _name_score(reference, node) > 0


def _numeric_tolerance(value: float) -> float:
    """Use a relative tolerance without collapsing all sub-unit decimals to one bucket."""
    magnitude = abs(value)
    if magnitude >= 10:
        return max(0.5, magnitude * 0.03)
    if magnitude >= 1:
        return max(0.05, magnitude * 0.03)
    return max(0.005, magnitude * 0.03)


def _value_score(
    reference: str,
    node: CandidateNode,
    reference_numbers: Iterable[float] | None = None,
) -> float:
    if not reference or not node.value_text:
        return 0.0
    ref_numbers = list(reference_numbers) if reference_numbers is not None else numbers(reference)
    node_numbers = node.cached("value_numbers", lambda: numbers(node.value_text))
    if ref_numbers:
        best = 0.0
        for left in ref_numbers:
            for right in node_numbers:
                tolerance = _numeric_tolerance(left)
                if abs(left - right) <= tolerance:
                    best = max(best, 1.0)
                    continue
                if right == 0:
                    continue
                for exponent in range(-6, 7):
                    if exponent == 0:
                        continue
                    if abs(left - right * (10.0 ** exponent)) <= tolerance:
                        best = max(best, 0.9)
        return best
    overlap = _canonical_terms(reference) & _canonical_terms(node.value_text)
    return 0.75 if overlap else 0.0


def _method_score(reference: str, node: CandidateNode) -> float | None:
    expected = _canonical_methods(reference)
    if not expected:
        return None
    actual = node.cached("method_terms", lambda: _canonical_methods(node.method_text))
    return 1.0 if expected & actual else 0.0


def _condition_score(reference: str, node: CandidateNode) -> float | None:
    ref_numbers = numbers(reference)
    ref_terms = _canonical_terms(reference)
    if not ref_numbers and not any(term in ref_terms for term in ("temperature", "pressure", "solvent", "atmosphere", "frequency", "humidity", "processing")):
        return None
    if not node.condition_text:
        return 0.0
    if ref_numbers:
        node_numbers = node.cached("condition_numbers", lambda: numbers(node.condition_text))
        for left in ref_numbers:
            for right in node_numbers:
                tolerance = _numeric_tolerance(left)
                if abs(left - right) <= tolerance:
                    return 1.0
                if right and any(
                    abs(left - right * (10.0 ** exponent)) <= tolerance
                    for exponent in range(-6, 7) if exponent != 0
                ):
                    return 0.9
        return 0.0
    node_terms = node.cached("condition_terms", lambda: _canonical_terms(node.condition_text))
    return 0.75 if ref_terms & node_terms else 0.0


def _shared_anchors(left: CandidateNode, right: CandidateNode) -> tuple[float, list[dict[str, str]]]:
    if left.node_id == right.node_id:
        return 1.0, []
    matches: list[dict[str, str]] = []
    strong = 0
    medium = 0
    for kind in set(left.anchors) & set(right.anchors):
        for value in left.anchors[kind] & right.anchors[kind]:
            strength = "strong" if kind in STRONG_ANCHORS else "medium" if kind in MEDIUM_ANCHORS else "weak"
            matches.append({"type": kind, "value": value, "strength": strength})
            if strength == "strong":
                strong += 1
            elif strength == "medium":
                medium += 1
    if strong:
        return 1.0, matches
    if medium >= 2:
        return 0.75, matches
    if medium == 1:
        return 0.6, matches
    return 0.0, matches


def _can_combine(left: CandidateNode, right: CandidateNode) -> tuple[bool, float, list[dict[str, str]]]:
    strength, anchors = _shared_anchors(left, right)
    # 不用页码或同一个数字把两个对象强行拼接。
    return strength >= 0.6, strength, anchors


def _best_related(
    index: CandidateIndex,
    base_nodes: Iterable[CandidateNode],
    descriptor: AuditDescriptor,
    component: str,
    scored_nodes: Iterable[tuple[CandidateNode, float]] | None = None,
) -> tuple[CandidateNode | None, float | None, list[dict[str, str]]]:
    best: tuple[float, CandidateNode, list[dict[str, str]]] | None = None
    base = list(base_nodes)
    if scored_nodes is None:
        candidates = []
        for node in index.nodes:
            score = _method_score(descriptor.method_text, node) if component == "method" else _condition_score(descriptor.condition_text, node)
            if score is not None and score > 0:
                candidates.append((node, score))
    else:
        candidates = list(scored_nodes)
    for node, score in candidates:
        for base_node in base:
            can_combine, anchor_strength, anchors = _can_combine(base_node, node)
            if can_combine:
                total = score + anchor_strength * 0.1
                if best is None or total > best[0]:
                    best = (total, node, anchors)
    if best is None:
        return None, None, []
    return best[1], best[0], best[2]


def _evidence_only_decision(descriptor: AuditDescriptor, index: CandidateIndex) -> dict[str, Any] | None:
    best: tuple[float, CandidateNode] | None = None
    for node in index.nodes:
        if not node.evidence_only:
            continue
        score = _value_score(descriptor.value_text, node, descriptor.primary_numbers)
        if score > 0 and (best is None or score > best[0]):
            best = (score, node)
    if best is None:
        return None
    return {
        "match_status": "evidence_only",
        "match_tier": "evidence_only",
        "score": round(best[0], 4),
        "parts": {"evidence": best[1].ref()},
        "anchors": [
            {"type": kind, "value": value, "strength": "medium" if kind in MEDIUM_ANCHORS else "strong"}
            for kind, values in best[1].anchors.items() for value in sorted(values)
        ],
        "reasons": ["evidence_text_matches_but_no_structured_value_object"],
    }


def match_audit_row(row: Mapping[str, Any], index: CandidateIndex) -> dict[str, Any]:
    """Return an auditable composite decision for one PolyInfo audit row."""
    descriptor = describe_audit_row(row)
    value_nodes = []
    for node in index.nodes:
        if node.evidence_only or node.collection not in descriptor.expected_value_collections:
            continue
        value_score = _value_score(descriptor.value_text, node, descriptor.primary_numbers)
        if value_score > 0:
            # 同一锚点下可能有多个相同数字；性质/工艺语义匹配用于稳定排序，
            # 但不作为硬过滤，避免字段命名差异造成漏报。
            semantic_score = _name_score(descriptor.semantic_text, node)
            if semantic_score > 0 and node.kind in {"value", "process", "condition", "method"}:
                value_score += 0.08 * semantic_score
            value_nodes.append((node, value_score))
    name_nodes = [
        (node, _name_score(descriptor.name_text, node))
        for node in index.nodes
        if not node.evidence_only
        and node.collection in (
            descriptor.expected_name_collections
            | ({"samples", "material_mentions", "polymer_entities"} if descriptor.sample_text else set())
        )
        and (
            not descriptor.sample_text
            or _sample_compatible(descriptor.sample_text, node)
        )
        and _name_score(descriptor.name_text, node) > 0
    ]

    name_by_id = {node.node_id: (node, score) for node, score in name_nodes}
    method_candidates = [
        (node, score)
        for node in index.nodes
        if (score := _method_score(descriptor.method_text, node)) is not None and score > 0
    ]
    condition_candidates = [
        (node, score)
        for node in index.nodes
        if (score := _condition_score(descriptor.condition_text, node)) is not None and score > 0
    ]
    bundles: list[dict[str, Any]] = []
    for value_node, value_score in value_nodes:
        related_names: dict[str, tuple[CandidateNode, float]] = {}
        if value_node.node_id in name_by_id:
            related_names[value_node.node_id] = name_by_id[value_node.node_id]
        for related_node in index.related(value_node):
            if related_node.node_id in name_by_id:
                related_names[related_node.node_id] = name_by_id[related_node.node_id]
        for name_node, name_score in related_names.values():
            can_combine, anchor_strength, anchors = _can_combine(value_node, name_node)
            if not can_combine:
                continue
            method_node, method_score, method_anchors = _best_related(
                index, (value_node, name_node), descriptor, "method", method_candidates
            )
            condition_node, condition_score, condition_anchors = _best_related(
                index, (value_node, name_node), descriptor, "condition", condition_candidates
            )
            expected_method = _canonical_methods(descriptor.method_text)
            expected_condition = numbers(descriptor.condition_text)
            required_ok = (not expected_method or method_score is not None) and (
                not expected_condition or condition_score is not None
            )
            method_component = method_score if method_score is not None else 0.0
            condition_component = condition_score if condition_score is not None else 0.0
            name_samples = set(name_node.anchors.get("sample_id", set()))
            value_samples = set(value_node.anchors.get("sample_id", set()))
            if name_samples and value_samples:
                sample_specificity = 0.05 if value_samples <= name_samples else 0.015
            elif name_samples:
                sample_specificity = -0.02
            else:
                sample_specificity = 0.0
            score = (
                0.45 * name_score
                + 0.4 * value_score
                + 0.1 * method_component
                + 0.05 * anchor_strength
                + sample_specificity
            )
            parts = {"name": name_node.ref(), "value": value_node.ref()}
            if method_node is not None:
                parts["method"] = method_node.ref()
            if condition_node is not None:
                parts["condition"] = condition_node.ref()
            bundles.append({
                "score": score,
                "name_score": name_score,
                "value_score": value_score,
                "anchor_strength": anchor_strength,
                "anchors": anchors + method_anchors + condition_anchors,
                "parts": parts,
                "required_ok": required_ok,
                "has_method": method_node is not None,
                "has_condition": condition_node is not None,
                "value_semantic_terms": sorted(
                    _canonical_terms(value_node.name_text) & _canonical_terms(descriptor.semantic_text)
                ),
                "value_sample_anchors": sorted(value_node.anchors.get("sample_id", set())),
            })

    if bundles:
        bundles.sort(key=lambda item: item["score"], reverse=True)
        best = bundles[0]
        tied = [item for item in bundles[1:] if abs(item["score"] - best["score"]) < 0.05]
        best_is_same_object = best["parts"].get("name") == best["parts"].get("value")
        def conflicts_with_best(item: Mapping[str, Any]) -> bool:
            if item["parts"].get("value") == best["parts"].get("value"):
                return False
            shared_terms = set(item.get("value_semantic_terms") or ()) & set(best.get("value_semantic_terms") or ())
            if shared_terms:
                left_samples = set(item.get("value_sample_anchors") or ())
                right_samples = set(best.get("value_sample_anchors") or ())
                if not left_samples or not right_samples or left_samples & right_samples:
                    return False
            return True

        competing_cross_object = not best_is_same_object and any(conflicts_with_best(item) for item in tied)
        if competing_cross_object:
            status = "ambiguous"
            tier = "cross_object_ambiguous"
            reasons = ["multiple_anchored_bundles_have_similar_scores"]
        elif best["required_ok"]:
            status = "composite_match"
            tier = "same_object" if best["anchor_strength"] == 1.0 and best["parts"]["name"] == best["parts"]["value"] else "cross_object"
            reasons = ["name_value_share_anchor"]
        else:
            status = "partial_match"
            tier = "cross_object_partial"
            reasons = ["name_value_share_anchor", "method_or_condition_not_resolved"]
        return {
            "match_status": status,
            "match_tier": tier,
            "score": round(best["score"], 4),
            "parts": best["parts"],
            "anchors": best["anchors"],
            "reasons": reasons,
        }

    evidence = _evidence_only_decision(descriptor, index)
    if evidence is not None:
        return evidence
    if value_nodes and name_nodes:
        reason = "name_value_without_shared_anchor"
    elif value_nodes:
        reason = "value_found_but_name_not_compatible"
    elif name_nodes:
        reason = "name_found_but_value_not_compatible"
    else:
        reason = "no_name_or_value_object"
    return {
        "match_status": "unmatched",
        "match_tier": "none",
        "score": 0.0,
        "parts": {},
        "anchors": [],
        "reasons": [reason],
    }


def match_audit_rows(rows: Iterable[Mapping[str, Any]], index: CandidateIndex) -> list[dict[str, Any]]:
    return [match_audit_row(row, index) for row in rows]


def summarize_decisions(decisions: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    summary = {
        "composite_match": 0,
        "partial_match": 0,
        "evidence_only": 0,
        "ambiguous": 0,
        "unmatched": 0,
    }
    for decision in decisions:
        status = str(decision.get("match_status") or "unmatched")
        summary[status] = summary.get(status, 0) + 1
    return summary

"""Stage 4T 表级 Shadow 抽取器。

本模块只做确定性的表格绑定，不调用 LLM，也不发布最终 Stage 4
PropertyObservation。输出保留原始样品标签、性质列语义和 cell locator，
供后续 Sample 解析、列级语义映射和人工复核使用。
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from schema.polymer_schema import Stage0Document, Stage0Element, Stage0TableCell
from stages.stage4r_table_recovery import infer_unit_from_headers
from stages.stage4t_candidate_gate import (
    assess_publication_candidate,
    semantic_classification,
)
from stages.stage4t_table_survey import (
    _COMPOSITION_AXIS_RE,
    _cell_at,
    _grid_shape,
    _is_value_like_numeric,
    _load_property_patterns,
    _normalized_text,
    _property_header_like,
    _property_match,
    _sample_like,
    _stage4t_header_rows,
    _unit_hits,
    survey_table,
)
from stages.table_grid import table_cells_for


SHADOW_VERSION = "0.5.0"
_SAMPLE_AXIS_WORD_RE = re.compile(
    r"\b(?:samples?|polymers?|specimens?|resins?|compounds?|blends?|runs?|codes?[a-z]?|no\.?|编号|样品|试样)\b",
    re.IGNORECASE,
)
_MEASUREMENT_ROLE_RE = re.compile(r"^(?:calcd|calculated|found)$", re.IGNORECASE)
_STATE_VALUE_RE = re.compile(
    r"^\s*(ox|red)\s*=\s*[+-]?(?:\d+(?:\.\d*)?|\.\d+)\s*$",
    re.IGNORECASE,
)
_CATEGORICAL_VALUES = {
    "amorphous",
    "crystal",
    "crystalline",
    "insoluble",
    "partially soluble",
    "semicrystalline",
    "semi-crystalline",
    "soluble",
}
_SOLUBILITY_SYMBOL_VARIANTS = {
    "+": "soluble",
    "++": "soluble",
    "+-": "partially_soluble",
    "±": "partially_soluble",
    "-": "insoluble",
}
_NON_OBSERVATION_HEADER_RE = re.compile(
    r"\b(?:amount\s+used|appearance|catalyst|column\s+loading|comment|description|"
    r"comments?|dissolved\s+in|feed\s+ratio|reaction\s+time|sample\s*id|"
    r"solvent|unit\s+ratio|yield)\b|\bmmol\b|"
    r"\b(?:oda|ppda|btc)\s+(?:fraction|%)\b|\bpolymer\s*\|\s*codes?[a-z]?\b|"
    r"投料|催化剂|溶剂|产率|备注|描述",
    re.IGNORECASE,
)
_FOOTNOTE_VALUE_RE = re.compile(
    r"\^\s*\{?\s*[a-z]\s*\}?|(?<=\d)\s*[a-z]\s*$",
    re.IGNORECASE,
)
_FOOTNOTED_DEGREE_VALUE_RE = re.compile(
    r"^\s*\$?\s*[<>]?\s*[+-]?(?:\d+(?:\.\d*)?|\.\d+)\s*"
    r"\^\s*\{\s*(?:°|\\circ|\\degree)\s*[a-z]\)?\s*\}\s*\$?\s*$",
    re.IGNORECASE,
)


def _text(cell: Stage0TableCell | None) -> str:
    return cell.text.strip() if cell is not None else ""


def _header_context(
    cells: Sequence[Stage0TableCell],
    header_rows: set[int],
    row: int,
    column: int,
) -> list[str]:
    values: list[str] = []
    for header_row in sorted(header_rows):
        cell = _cell_at(cells, header_row, column)
        if cell is not None and cell.text.strip():
            values.append(cell.text.strip())
    return values


def _unit_info(headers: Sequence[str], caption: str | None) -> dict[str, Any]:
    header_units = _unit_hits(" | ".join(headers))
    caption_units = _unit_hits(caption or "")
    raw = header_units[0] if header_units else (
        caption_units[0] if caption_units else None
    )
    normalized = infer_unit_from_headers(headers)
    if normalized is None and caption:
        normalized = infer_unit_from_headers([caption])
    locations = []
    if header_units:
        locations.append("header")
    if caption_units:
        locations.append("caption")
    return {
        "unit_raw": raw,
        "unit_normalized": normalized,
        "unit_location": (
            locations[0] if len(locations) == 1
            else "multiple" if locations else "not_found"
        ),
    }


def _sample_label_for_row(
    cells: Sequence[Stage0TableCell],
    header_rows: set[int],
    row: int,
    property_column: int,
) -> str | None:
    explicit_columns: set[int] = set()
    composition_columns: set[int] = set()
    for header in cells:
        normalized_header = _normalized_text(header.text)
        if (
            header.row_index not in header_rows
            or header.column_index >= property_column
            or not (
                _SAMPLE_AXIS_WORD_RE.search(normalized_header)
                or _COMPOSITION_AXIS_RE.search(normalized_header)
            )
        ):
            continue
        has_child_headers = any(
            child.row_index in header_rows
            and child.row_index > header.row_index
            and header.column_index <= child.column_index
            and child.column_index < header.column_index + header.column_span
            for child in cells
        )
        if header.column_span > 1 and has_child_headers:
            continue
        explicit_columns.update(
            range(
                header.column_index,
                min(header.column_index + header.column_span, property_column),
            )
        )
        if _COMPOSITION_AXIS_RE.search(normalized_header):
            composition_columns.update(
                range(
                    header.column_index,
                    min(header.column_index + header.column_span, property_column),
                )
            )
    explicit_values: list[str] = []
    for column in sorted(explicit_columns):
        value = _text(_cell_at(cells, row, column))
        if value and value not in explicit_values:
            explicit_values.append(value)
    if explicit_values:
        if all(_MEASUREMENT_ROLE_RE.fullmatch(value) for value in explicit_values):
            for prior_row in range(row - 1, max(header_rows, default=-1), -1):
                group = _cell_at(cells, prior_row, min(explicit_columns))
                if (
                    group is not None
                    and group.row_index == prior_row
                    and group.column_span > 1
                    and _sample_like(group.text)
                ):
                    return group.text.strip()
        if composition_columns and all(
            _is_value_like_numeric(value) for value in explicit_values
        ):
            data_start = max(header_rows, default=-1) + 1
            has_named_control = any(
                cell.row_index >= data_start
                and cell.column_index in composition_columns
                and cell.text.strip()
                and not _is_value_like_numeric(cell.text)
                and _sample_like(cell.text)
                for cell in cells
            )
            if has_named_control:
                return None
        return " | ".join(explicit_values)

    candidates = [
        cell for cell in cells
        if cell.row_index <= row < cell.row_index + cell.row_span
        and cell.column_index < property_column
        and cell.text.strip()
        and not _is_value_like_numeric(cell.text)
        and not _STATE_VALUE_RE.fullmatch(cell.text)
        and _sample_like(cell.text)
    ]
    if not candidates:
        for prior_row in range(row - 1, max(header_rows, default=-1), -1):
            prior = _cell_at(cells, prior_row, 0)
            if (
                prior is not None
                and prior.row_index == prior_row
                and _sample_like(prior.text)
                and not _MEASUREMENT_ROLE_RE.fullmatch(prior.text.strip())
            ):
                return prior.text.strip()
        return None
    return max(candidates, key=lambda cell: cell.column_index).text.strip()


def _match_property(
    text: str,
    patterns: Sequence[tuple[re.Pattern[str], str]],
) -> str | None:
    normalized = _normalized_text(text)
    normalized = re.sub(r"\bt\s+dec\b", "t d", normalized)
    normalized = re.sub(r"\btga\s*[-:]?\s*(\d+(?:\.\d+)?)\s*%", r"t \1%", normalized)
    return _property_match(normalized, patterns)


def _property_semantics(
    text: str,
    patterns: Sequence[tuple[re.Pattern[str], str]],
    *,
    table_context: str = "",
) -> dict[str, Any]:
    normalized = _normalized_text(text)
    normalized_context = _normalized_text(table_context)
    property_name = _match_property(text, patterns)
    semantic_label: str | None = None
    property_variant: str | None = None
    conditions: dict[str, Any] = {}

    if property_name is None and re.search(r"(?:^|\W)t\s+i(?:\W|$)", normalized):
        degradation_context = re.search(
            r"\bt\s+\d+(?:\.\d+)?\b|\bt\s+max\b|\bchar\s+yield\b|"
            r"\btga\b|\bdecompos|\bdegrad|\bweight\s+loss\b",
            normalized_context,
        )
        if degradation_context:
            property_name = "thermal_decomposition_temperature"
            property_variant = "initial_decomposition"
        else:
            semantic_label = "transition_temperature_ti"
    elif property_name is None and re.search(r"(?:^|\W)t\s+max(?:\W|$)", normalized):
        property_name = "thermal_decomposition_temperature"
        property_variant = "maximum_decomposition_rate"
    elif property_name is None:
        threshold = re.search(r"(?:^|\W)t\s+(\d+(?:\.\d+)?)(?:\W|$)", normalized)
        if threshold:
            property_name = "thermal_decomposition_temperature"
            property_variant = "mass_loss_threshold"
            conditions["mass_loss_percent"] = float(threshold.group(1))

    if re.search(r"\bchar\s+yield\b|\bchar\s+residue\b|残炭率|残碳率", normalized):
        property_name = None
        semantic_label = "char_yield"
        temperature = re.search(r"\bat\s+(\d+(?:\.\d+)?)\s*°?\s*c\b", normalized)
        if temperature:
            conditions["temperature_celsius"] = float(temperature.group(1))

    viscosity_variants = (
        (r"\binherent\s+viscosity\b|(?:\\eta|eta|η)\s*inh\b", "inherent"),
        (r"\bintrinsic\s+viscosity\b|\[\s*(?:eta|η)\s*\]|(?:\\eta|eta|η)\s*int\b", "intrinsic"),
        (r"\breduced\s+viscosity\b|(?:\\eta|eta|η)\s*red\b", "reduced"),
        (r"\bspecific\s+viscosity\b|(?:\\eta|eta|η)\s*sp\b", "specific"),
    )
    if property_name == "intrinsic_viscosity":
        property_variant = next(
            (variant for pattern, variant in viscosity_variants if re.search(pattern, normalized)),
            property_variant,
        )

    molecular_weight_distribution = re.search(
        r"m\s+[nw]\s*/(?:\\overline\s*)?m\s+[nw]|"
        r"\bpdi\b|\bpolydispersity\b|\bdispersity\b|đ",
        normalized,
    )
    if property_name is None and molecular_weight_distribution:
        semantic_label = "molecular_weight_distribution"

    molecular_weight = re.search(
        r"(?:^|\W)m\s+(n|w|z|v)(?:\W|$)|"
        r"\b(number|weight|z|viscosity)[ -]average\s+molecular\s+weight\b",
        normalized,
    )
    if property_name is None and molecular_weight and semantic_label is None:
        token = molecular_weight.group(1) or molecular_weight.group(2)
        variant_by_token = {
            "n": "number_average", "number": "number_average",
            "w": "weight_average", "weight": "weight_average",
            "z": "z_average", "v": "viscosity_average", "viscosity": "viscosity_average",
        }
        semantic_label = "molecular_weight"
        property_variant = variant_by_token[token]

    if property_name is None and re.search(r"\b(?:degree\s+of\s+)?crystal\s*-?\s*linity\b|结晶度", normalized):
        semantic_label = "crystallinity"

    if property_name is None and semantic_label is None and re.search(
        r"\bsolubility\b|溶解性",
        normalized,
    ):
        semantic_label = "solubility"

    if property_name is None and semantic_label is None and re.search(
        r"\belemental\s+analysis\b",
        normalized,
    ):
        element = re.search(r"(?:^|\W)(c|h|n|o|s)(?:\W|$)", normalized)
        semantic_label = "elemental_composition"
        property_variant = element.group(1) if element else None

    if property_name is None and semantic_label is None and re.search(
        r"\bir\b|infrared",
        normalized,
    ) and re.search(r"cm\s*\^?\s*-?\s*1|kbr", normalized):
        semantic_label = "infrared_absorption_peak"

    if property_name is None and semantic_label is None and re.search(
        r"\bnmr\b|chemical\s+shift",
        normalized,
    ):
        semantic_label = "nmr_chemical_shift"

    if property_name is None and semantic_label is None and re.search(
        r"(?:λ|lambda)\s*max|absorption\s+(?:peak|wavelength)",
        normalized,
    ):
        semantic_label = "absorption_wavelength"

    if property_name is None and semantic_label is None and re.search(
        r"(?:λ|lambda)\s*em|emission\s+(?:peak|wavelength)",
        normalized,
    ):
        semantic_label = "emission_wavelength"

    if property_name is None and semantic_label is None and re.search(
        r"(?:^|\W)(?:φ|phi)(?:\W|$)|quantum\s+yield",
        normalized,
    ):
        semantic_label = "quantum_yield"

    if property_name is None and semantic_label is None and re.search(
        r"(?:^|\W)(?:ε|epsilon)(?:\W|$)|molar\s+(?:extinction|absorption)",
        normalized,
    ):
        semantic_label = "molar_extinction_coefficient"

    if property_name is None and semantic_label is None and re.search(
        r"(?:^|\W)dp(?:\W|$)|degree\s+of\s+polymerization",
        normalized,
    ):
        semantic_label = "degree_of_polymerization"

    if property_name is None and semantic_label is None and re.search(
        r"dn\s*/\s*dc|refractive\s+index\s+increment",
        normalized,
    ):
        semantic_label = "refractive_index_increment"

    if property_name is None and semantic_label is None and re.search(
        r"(?:^|\W)r\s*h(?:\W|$)|hydrodynamic\s+radius",
        normalized,
    ):
        semantic_label = "hydrodynamic_radius"

    if property_name is None and semantic_label is None and re.search(
        r"\bvoid\s+(?:content|fraction)\b",
        normalized,
    ):
        semantic_label = "void_fraction"

    if property_name is None and semantic_label is None and re.search(
        r"\bfiber\s+orientation\b|(?:^|\W)f\s*[tlw](?:\W|$)",
        normalized,
    ):
        semantic_label = "fiber_orientation_factor"

    if property_name is None and semantic_label is None and re.search(
        r"\bporosity\b",
        normalized,
    ):
        semantic_label = "porosity"

    if property_name is None and semantic_label is None and re.search(
        r"\bshrinkage\b",
        normalized,
    ):
        semantic_label = "shrinkage"

    if property_name is None and semantic_label is None and re.search(
        r"\bspecific\s+gravity\b",
        normalized,
    ):
        semantic_label = "density"
        property_variant = "specific_gravity"

    if property_name is None and semantic_label is None and re.search(
        r"\bbulk\s+density\b",
        normalized,
    ):
        semantic_label = "density"
        property_variant = "bulk_density"

    filler_geometry = (
        (r"\baggregate\s+size\b", "aggregate_size"),
        (r"\bfiber\s+diameter\b", "fiber_diameter"),
        (r"\bpore\s+volume\b", "pore_volume"),
    )
    if property_name is None and semantic_label is None:
        geometry_variant = next(
            (variant for pattern, variant in filler_geometry if re.search(pattern, normalized)),
            None,
        )
        if geometry_variant:
            semantic_label = "filler_geometry"
            property_variant = geometry_variant

    if property_name is None and semantic_label is None and re.search(
        r"\bsurface\s+area\b",
        normalized,
    ):
        semantic_label = "specific_surface_area"

    if property_name is None and semantic_label is None and re.search(
        r"\bfiber\s+length\b",
        normalized,
    ):
        semantic_label = "fiber_length"

    diffraction_context = bool(re.search(
        r"\bx\s*-?\s*ray\b|\bxrd\b|\bwaxd\b|diffraction",
        normalized_context,
    ))
    if property_name is None and semantic_label is None and diffraction_context:
        if re.search(r"2\s*(?:theta|θ)", normalized):
            semantic_label = "xray_diffraction_peak"
            property_variant = "two_theta"
        elif normalized.strip() == "d":
            semantic_label = "d_spacing"
        elif re.search(r"i\s*/\s*i\s*0", normalized):
            semantic_label = "relative_intensity"

    if property_name is None and semantic_label is None and re.search(
        r"(?:^|\W)r\s*[fa](?:\W|$)",
        normalized,
    ):
        semantic_label = "composition_ratio"
        property_variant = "feed" if re.search(r"r\s*f", normalized) else "actual"

    interaction = re.search(r"(?:χ|chi)\s*(12|23)?", normalized)
    if property_name is None and semantic_label is None and interaction:
        semantic_label = {
            "12": "polymer_solvent_interaction_parameter",
            "23": "polymer_polymer_interaction_parameter",
        }.get(interaction.group(1), "interaction_parameter")

    if re.search(r"\bcell\s+density\b|泡孔密度", normalized):
        property_name = None
        semantic_label = "cell_density"

    if property_name is None and re.search(r"\b(?:wt|weight|mass)\s+loss\b|失重率|质量损失", normalized):
        semantic_label = "mass_loss_fraction"

    if property_name is None and (
        (re.search(r"(?:^|\W)rm(?:\W|$)", normalized) and "%" in normalized)
        or re.search(r"%\s*residue\b|\bresidual\s+mass\b", normalized)
    ):
        semantic_label = "residual_mass_fraction"
        temperature = re.search(r"\bat\s+(\d+(?:\.\d+)?)\s*°?\s*c\b", normalized)
        if temperature:
            conditions["temperature_celsius"] = float(temperature.group(1))

    if property_name is None and semantic_label is None and re.search(
        r"\b(?:av|avg|average)\.?\s+molar\s+mass\b",
        normalized,
    ):
        semantic_label = "molecular_weight"

    if property_name is None and semantic_label is None and re.search(
        r"\b(?:wt|weight)\.?\s+average\s+(?:fiber\s+)?length\b",
        normalized,
    ):
        semantic_label = "fiber_length"
        property_variant = "weight_average"

    if (
        property_name is None
        and semantic_label is None
        and re.search(r"\belectrochromic\b", normalized_context)
        and normalized.strip() in {"l", "a", "b"}
    ):
        semantic_label = "electrochromic_color_coordinate"
        property_variant = f"cie_lab_{normalized.strip()}"

    relaxation_context = bool(re.search(
        r"\brelaxation\b|\bfuoss\b|\bhavriliak\b|\bnegami\b",
        normalized_context,
    ))
    if relaxation_context and property_name != "electric_conductivity":
        property_name = None
        semantic_label = "dielectric_relaxation_parameter"
        if "delta" in normalized or "ε" in normalized:
            property_variant = "relaxation_strength"
        elif re.search(r"(?:τ|tau)\s*max|t\s+max", normalized):
            property_variant = "peak_relaxation_time"
        elif "τ" in normalized or re.search(r"\btau\b", normalized):
            property_variant = "relaxation_time"
        elif re.search(r"(?:^|\W)m(?:\W|$)", normalized):
            property_variant = "fuoss_kirkwood_m"
        elif normalized.strip() == "s":
            property_variant = "frequency_exponent_s"
        elif normalized.strip() in {"μ", "mu"}:
            property_variant = "havriliak_negami_mu"
        elif normalized.strip() in {"ν", "nu"}:
            property_variant = "havriliak_negami_nu"
        if "beta" in normalized:
            property_variant = f"{property_variant or 'parameter'}_beta"
        elif "gamma" in normalized:
            property_variant = f"{property_variant or 'parameter'}_gamma"

    if property_name == "thermal_decomposition_temperature":
        threshold = re.search(
            r"(?:t\s+d|tga)\s*(?:\^\s*)?[-:]?\s*(\d+(?:\.\d+)?)\s*\\?%",
            normalized,
        )
        if threshold:
            property_variant = "mass_loss_threshold"
            conditions["mass_loss_percent"] = float(threshold.group(1))
        elif re.search(r"t\s+d\s*\^\s*i(?:\W|$)", normalized):
            property_variant = "initial_decomposition"

    return {
        "property_name_normalized": property_name,
        "semantic_label": semantic_label,
        "property_variant": property_variant,
        "conditions": conditions,
    }


def _observation(
    *,
    table_id: str,
    cell: Stage0TableCell,
    sample_label: str | None,
    property_raw: str,
    property_name: str | None,
    semantic_label: str | None,
    property_variant: str | None,
    conditions: Mapping[str, Any],
    unit: Mapping[str, Any],
    direction: str,
    measurement_role: str = "reported_unknown",
    header_column_index: int | None = None,
    alignment_status: str = "exact",
    header_path: Sequence[str] | None = None,
    axis_role: str | None = None,
) -> dict[str, Any]:
    value_raw = cell.text.strip()
    categorical = _categorical_value(value_raw)
    if categorical in {"soluble", "insoluble", "partially soluble"}:
        property_name = None
        semantic_label = "solubility"
        property_variant = categorical.replace(" ", "_")
    elif categorical in {
        "amorphous",
        "crystal",
        "crystalline",
        "semicrystalline",
        "semi-crystalline",
    }:
        property_name = None
        semantic_label = "crystallinity"
        property_variant = categorical.replace("-", "_")
    semantic_status, candidate_class, publication_target = semantic_classification(
        property_name,
        semantic_label,
    )
    value_kind = _value_kind(value_raw)
    if measurement_role == "calculated":
        candidate_role = "calculated_result"
    elif property_name:
        candidate_role = "property_candidate"
    elif semantic_label:
        candidate_role = "material_characteristic"
    elif value_kind.startswith("numeric") or value_kind == "state_qualified_numeric":
        candidate_role = "unknown_numeric"
    else:
        candidate_role = "unknown_observation"
    warnings: list[str] = []
    if property_name is None and semantic_label is None:
        warnings.append("semantic_unmapped")
    if sample_label is None and direction != "condition_series":
        warnings.append("sample_binding_unresolved")
    if value_kind in {
        "numeric_range",
        "numeric_multiple",
        "numeric_with_uncertainty",
        "state_qualified_numeric",
    }:
        warnings.append("value_structure_unvalidated")
    if _FOOTNOTE_VALUE_RE.search(value_raw):
        warnings.append("footnote_unresolved")
    locator = {
        "source": "table",
        "table_id": table_id,
        "cell_id": cell.cell_id,
        "row_index": cell.row_index,
        "column_index": cell.column_index,
        "header_path": list(header_path or ([property_raw] if property_raw else [])),
        "axis_role": axis_role or direction,
    }
    item = {
        "observation_id": f"{table_id}:{cell.cell_id}",
        "table_id": table_id,
        "direction": direction,
        "sample_label_raw": sample_label,
        "property_name_raw": property_raw,
        "property_name_normalized": property_name,
        "semantic_label": semantic_label,
        "property_variant": property_variant,
        "semantic_status": semantic_status,
        "candidate_class": candidate_class,
        "candidate_role": candidate_role,
        "candidate_state": "raw_candidate",
        "authority_target": publication_target,
        "conditions": dict(conditions),
        "measurement_role": measurement_role,
        "value_raw": value_raw,
        "value_kind": value_kind,
        "value_has_footnote": bool(_FOOTNOTE_VALUE_RE.search(value_raw)),
        "unit_raw": unit.get("unit_raw"),
        "unit_normalized": unit.get("unit_normalized"),
        "unit_location": unit.get("unit_location"),
        "cell_id": cell.cell_id,
        "row_index": cell.row_index,
        "column_index": cell.column_index,
        "header_column_index": (
            cell.column_index if header_column_index is None else header_column_index
        ),
        "alignment_status": alignment_status,
        "binding_status": "bound" if sample_label and property_name else "unresolved",
        "evidence": {
            "table_id": table_id,
            "cell_id": cell.cell_id,
            "row_index": cell.row_index,
            "column_index": cell.column_index,
        },
        "evidence_locator": locator,
        "warnings": warnings,
    }
    item["publication_gate"] = assess_publication_candidate(item)
    return item


def _numeric_scalar(text: str) -> float | None:
    match = re.search(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", text.replace(",", ""))
    return float(match.group(0)) if match else None


def _categorical_value(text: str) -> str | None:
    normalized = _normalized_text(text).strip(" .;:")
    return normalized if normalized in _CATEGORICAL_VALUES else None


def _solubility_symbol(text: str) -> str | None:
    return _SOLUBILITY_SYMBOL_VARIANTS.get((text or "").strip())


def _value_kind(text: str) -> str:
    if _STATE_VALUE_RE.fullmatch(text):
        return "state_qualified_numeric"
    if _categorical_value(text):
        return "categorical"
    if _solubility_symbol(text):
        return "categorical"
    normalized = text.replace(",", "")
    range_text = re.sub(
        r"(?:×|x|\\times)\s*10\s*[-−]\s*\d+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    numbers = re.findall(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", normalized)
    if "±" in text or re.search(r"\\pm\b", text):
        return "numeric_with_uncertainty"
    if len(numbers) >= 2 and re.search(r"\d\s*(?:/|,)\s*[+-]?\d", text):
        return "numeric_multiple"
    if len(numbers) >= 2 and re.search(r"\d\s*[-–—]\s*[+-]?\d", range_text):
        return "numeric_range"
    return "numeric_scalar"


def _candidate_value_like(text: str) -> bool:
    return bool(
        _is_value_like_numeric(text)
        or _STATE_VALUE_RE.fullmatch(text)
        or _categorical_value(text)
        or _FOOTNOTED_DEGREE_VALUE_RE.fullmatch(text)
    )


def _descriptor_is_observation_candidate(
    descriptor: Mapping[str, Any],
    *,
    allow_unmapped: bool,
) -> bool:
    if (
        descriptor.get("property_name_normalized") is not None
        or descriptor.get("semantic_label") is not None
    ):
        return True
    if not allow_unmapped:
        return False
    raw = str(descriptor.get("property_name_raw") or "").strip()
    return bool(raw and not _NON_OBSERVATION_HEADER_RE.search(_normalized_text(raw)))


def _measurement_role_for_row(
    cells: Sequence[Stage0TableCell],
    row: int,
    *,
    table_context: str = "",
) -> str:
    labels = {
        _normalized_text(cell.text)
        for cell in cells
        if cell.row_index <= row < cell.row_index + cell.row_span
        and cell.column_index <= 1
        and cell.text.strip()
    }
    if labels & {"calcd", "calculated"}:
        return "calculated"
    if "found" in labels:
        return "experimental"
    if re.search(
        r"\bcalculated\b|\bcomputed\b|\bmmx\b|\bforce\s+field\b|"
        r"molecular\s+mechanics|energy\s+minimi[sz]",
        _normalized_text(table_context),
    ):
        return "calculated"
    return "reported_unknown"


def _deduplicate_observations(
    observations: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    priority = {
        "official_property": 3,
        "material_characteristic": 2,
        "unknown_observation": 1,
    }
    by_cell: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in observations:
        cell_id = str(item["cell_id"])
        if cell_id not in by_cell:
            by_cell[cell_id] = item
            order.append(cell_id)
            continue
        current = by_cell[cell_id]
        if priority[item["candidate_class"]] > priority[current["candidate_class"]]:
            by_cell[cell_id] = item
    return [by_cell[cell_id] for cell_id in order]


def _unresolved_for_observations(
    observations: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    unresolved: list[dict[str, Any]] = []
    for item in observations:
        if item.get("sample_label_raw") is None and item.get("direction") != "condition_series":
            reason = "sample_label_not_found"
        elif item.get("property_name_normalized") is None:
            reason = "property_mapping_not_found"
        else:
            continue
        unresolved.append({
            "reason": reason,
            "cell_id": item["cell_id"],
            "row_index": item["row_index"],
            "column_index": item["column_index"],
            "property_name_raw": item.get("property_name_raw"),
            "semantic_label": item.get("semantic_label"),
        })
    return unresolved


def _value_cell_like(text: str) -> bool:
    return _candidate_value_like(text)


def _row_value_column(
    descriptor: Mapping[str, Any],
    cells: Sequence[Stage0TableCell],
    *,
    data_start: int,
    row_count: int,
    column_count: int,
) -> tuple[int, str]:
    column = int(descriptor["column_index"])
    if descriptor.get("property_name_normalized") != "intrinsic_viscosity":
        return column, "exact"
    if column + 1 >= column_count:
        return column, "exact"

    current_texts = [
        _text(_cell_at(cells, row, column)) for row in range(data_start, row_count)
    ]
    right_texts = [
        _text(_cell_at(cells, row, column + 1)) for row in range(data_start, row_count)
    ]
    current_values = [
        value for text in current_texts
        if _is_value_like_numeric(text) and (value := _numeric_scalar(text)) is not None
    ]
    right_values = [
        value for text in right_texts
        if _is_value_like_numeric(text) and (value := _numeric_scalar(text)) is not None
    ]
    has_viscosity_state = any(
        re.search(r"\binsoluble\b|\bnot\s+soluble\b|不溶", _normalized_text(text))
        for text in right_texts
    )
    if (
        len(current_values) >= 3
        and len(right_values) >= 3
        and min(current_values) > 50
        and max(right_values) <= 20
        and has_viscosity_state
    ):
        return column + 1, "inferred_right_shift"
    return column, "exact"


def _property_descriptor(
    *,
    table_id: str,
    column_index: int,
    headers: Sequence[str],
    caption: str | None,
    patterns: Sequence[tuple[re.Pattern[str], str]],
    direction: str,
    table_context: str = "",
) -> dict[str, Any]:
    raw = " | ".join(headers)
    semantics = _property_semantics(
        " | ".join(headers),
        patterns,
        table_context=table_context,
    )
    unit = _unit_info(headers, caption)
    return {
        "table_id": table_id,
        "column_index": column_index,
        "header_context": list(headers),
        "property_name_raw": raw,
        **semantics,
        "direction": direction,
        **unit,
    }


def _row_shadow(
    *,
    table: Stage0Element,
    cells: Sequence[Stage0TableCell],
    header_rows: set[int],
    patterns: Sequence[tuple[re.Pattern[str], str]],
    direction: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    row_count, column_count = _grid_shape(cells)
    table_context = " | ".join(
        [table.caption or ""]
        + [cell.text for cell in cells if cell.row_index in header_rows]
    )
    descriptors: list[dict[str, Any]] = []
    descriptor_keys: set[tuple[int, str]] = set()
    for column in range(column_count):
        headers = _header_context(cells, header_rows, 0, column)
        if not headers:
            continue
        descriptor = _property_descriptor(
            table_id=table.block_id,
            column_index=column,
            headers=headers,
            caption=table.caption,
            patterns=patterns,
            direction=direction,
            table_context=table_context,
        )
        descriptor_key = (column, descriptor["property_name_raw"])
        if descriptor_key not in descriptor_keys:
            descriptors.append(descriptor)
            descriptor_keys.add(descriptor_key)

    observations: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    data_start = max(header_rows, default=-1) + 1
    for descriptor in descriptors:
        header_column = int(descriptor["column_index"])
        if not _descriptor_is_observation_candidate(
            descriptor,
            allow_unmapped=header_column > 0,
        ):
            continue
        column, alignment_status = _row_value_column(
            descriptor,
            cells,
            data_start=data_start,
            row_count=row_count,
            column_count=column_count,
        )
        for row in range(data_start, row_count):
            cell = _cell_at(cells, row, column)
            if cell is None or not _value_cell_like(cell.text):
                continue
            sample_label = _sample_label_for_row(cells, header_rows, row, column)
            conditions = dict(descriptor["conditions"])
            if state_match := _STATE_VALUE_RE.fullmatch(cell.text):
                conditions["electrochemical_state"] = (
                    "oxidized" if state_match.group(1).lower() == "ox" else "reduced"
                )
            item = _observation(
                table_id=table.block_id,
                cell=cell,
                sample_label=sample_label,
                property_raw=descriptor["property_name_raw"],
                property_name=descriptor["property_name_normalized"],
                semantic_label=descriptor["semantic_label"],
                property_variant=descriptor["property_variant"],
                conditions=conditions,
                unit=descriptor,
                direction=direction,
                measurement_role=_measurement_role_for_row(
                    cells,
                    row,
                    table_context=table_context,
                ),
                header_column_index=header_column,
                alignment_status=alignment_status,
            )
            if sample_label is None:
                item["binding_status"] = "unresolved"
                unresolved.append({
                    "reason": "sample_label_not_found",
                    "cell_id": cell.cell_id,
                    "row_index": row,
                    "column_index": column,
                })
            elif descriptor["property_name_normalized"] is None:
                unresolved.append({
                    "reason": "property_mapping_not_found",
                    "cell_id": cell.cell_id,
                    "row_index": row,
                    "column_index": column,
                    "property_name_raw": descriptor["property_name_raw"],
                    "semantic_label": descriptor["semantic_label"],
                })
            observations.append(item)
    return descriptors, observations, unresolved


def _column_shadow(
    *,
    table: Stage0Element,
    cells: Sequence[Stage0TableCell],
    header_rows: set[int],
    patterns: Sequence[tuple[re.Pattern[str], str]],
    direction: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    row_count, column_count = _grid_shape(cells)
    header_row = min(header_rows, default=0)
    descriptors: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    descriptor_rows: set[int] = set()
    for column in range(1, column_count):
        sample_label = _text(_cell_at(cells, header_row, column))
        for row in range(max(header_rows, default=-1) + 1, row_count):
            property_cell = _cell_at(cells, row, 0)
            value_cell = _cell_at(cells, row, column)
            if property_cell is None or value_cell is None:
                continue
            property_raw = property_cell.text.strip()
            if not property_raw or not _candidate_value_like(value_cell.text):
                continue
            descriptor = _property_descriptor(
                table_id=table.block_id,
                column_index=0,
                headers=[property_raw],
                caption=table.caption,
                patterns=patterns,
                direction=direction,
                table_context=table.caption or "",
            )
            if not _descriptor_is_observation_candidate(
                descriptor,
                allow_unmapped=True,
            ):
                continue
            if row not in descriptor_rows:
                descriptors.append(descriptor)
                descriptor_rows.add(row)
            item = _observation(
                table_id=table.block_id,
                cell=value_cell,
                sample_label=sample_label or None,
                property_raw=property_raw,
                property_name=descriptor["property_name_normalized"],
                semantic_label=descriptor["semantic_label"],
                property_variant=descriptor["property_variant"],
                conditions=descriptor["conditions"],
                unit=descriptor,
                direction=direction,
                measurement_role=_measurement_role_for_row(
                    cells,
                    row,
                    table_context=table.caption or "",
                ),
            )
            if not sample_label:
                item["binding_status"] = "unresolved"
                unresolved.append({
                    "reason": "sample_label_not_found",
                    "cell_id": value_cell.cell_id,
                    "row_index": row,
                    "column_index": column,
                })
            elif descriptor["property_name_normalized"] is None:
                unresolved.append({
                    "reason": "property_mapping_not_found",
                    "cell_id": value_cell.cell_id,
                    "row_index": row,
                    "column_index": column,
                    "property_name_raw": property_raw,
                })
            observations.append(item)
    return descriptors, observations, unresolved


def _solubility_column_shadow(
    *,
    table: Stage0Element,
    cells: Sequence[Stage0TableCell],
    header_rows: set[int],
    direction: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """承接以 +/− 符号表示的定性溶解性表，不把符号泛化为数值。"""
    row_count, column_count = _grid_shape(cells)
    header_row = min(header_rows, default=0)
    data_start = max(header_rows, default=-1) + 1
    descriptors: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for column in range(1, column_count):
        solvent_cell = _cell_at(cells, header_row, column)
        solvent = _text(solvent_cell)
        if not solvent:
            continue
        descriptors.append({
            "table_id": table.block_id,
            "column_index": column,
            "header_context": [solvent],
            "property_name_raw": "Solubility",
            "property_name_normalized": None,
            "semantic_label": "solubility",
            "property_variant": None,
            "conditions": {"solvent": solvent},
            "direction": direction,
            "unit_raw": None,
            "unit_normalized": None,
            "unit_location": "not_applicable",
        })
        for row in range(data_start, row_count):
            sample_cell = _cell_at(cells, row, 0)
            value_cell = _cell_at(cells, row, column)
            variant = _solubility_symbol(_text(value_cell)) if value_cell else None
            if sample_cell is None or value_cell is None or variant is None:
                continue
            item = _observation(
                table_id=table.block_id,
                cell=value_cell,
                sample_label=_text(sample_cell) or None,
                property_raw="Solubility",
                property_name=None,
                semantic_label="solubility",
                property_variant=variant,
                conditions={"solvent": solvent},
                unit={
                    "unit_raw": None,
                    "unit_normalized": None,
                    "unit_location": "not_applicable",
                },
                direction=direction,
                header_path=["Solubility", solvent],
                axis_role="named_sample",
            )
            observations.append(item)
    return descriptors, observations, unresolved


def _grouped_column_shadow(
    *,
    table: Stage0Element,
    cells: Sequence[Stage0TableCell],
    header_rows: set[int],
    patterns: Sequence[tuple[re.Pattern[str], str]],
    direction: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    row_count, column_count = _grid_shape(cells)
    top_header = min(header_rows, default=0)
    sub_header = max(header_rows, default=top_header)
    descriptors: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    data_start = sub_header + 1

    for column in range(column_count):
        sample_cell = _cell_at(cells, top_header, column)
        property_cell = _cell_at(cells, sub_header, column)
        sample_label = _text(sample_cell) or None
        property_raw = _text(property_cell)
        if not sample_label or not property_raw:
            continue
        descriptor = _property_descriptor(
            table_id=table.block_id,
            column_index=column,
            headers=[property_raw],
            caption=table.caption,
            patterns=patterns,
            direction=direction,
            table_context=table.caption or "",
        )
        if not _descriptor_is_observation_candidate(
            descriptor,
            allow_unmapped=True,
        ):
            continue
        descriptors.append(descriptor)
        for row in range(data_start, row_count):
            value_cell = _cell_at(cells, row, column)
            if value_cell is None or not _candidate_value_like(value_cell.text):
                continue
            item = _observation(
                table_id=table.block_id,
                cell=value_cell,
                sample_label=sample_label,
                property_raw=property_raw,
                property_name=descriptor["property_name_normalized"],
                semantic_label=descriptor["semantic_label"],
                property_variant=descriptor["property_variant"],
                conditions=descriptor["conditions"],
                unit=descriptor,
                direction=direction,
            )
            if descriptor["property_name_normalized"] is None:
                unresolved.append({
                    "reason": "property_mapping_not_found",
                    "cell_id": value_cell.cell_id,
                    "row_index": row,
                    "column_index": column,
                    "property_name_raw": property_raw,
                    "semantic_label": descriptor["semantic_label"],
                })
            observations.append(item)
    return descriptors, observations, unresolved


def _condition_shadow(
    *,
    table: Stage0Element,
    cells: Sequence[Stage0TableCell],
    header_rows: set[int],
    patterns: Sequence[tuple[re.Pattern[str], str]],
    direction: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    row_count, column_count = _grid_shape(cells)
    data_start = max(header_rows, default=-1) + 1
    condition_header = " | ".join(_header_context(cells, header_rows, 0, 0))
    normalized_condition = _normalized_text(condition_header)
    if re.search(r"\bhz\b|\bfrequency\b", normalized_condition):
        condition_key = "frequency_hz"
    elif re.search(r"\(\s*k\s*\)|\btemperature\b", normalized_condition):
        condition_key = "temperature_kelvin"
    else:
        return [], [], []

    table_context = " | ".join(
        [table.caption or ""]
        + [cell.text for cell in cells if cell.row_index in header_rows]
    )
    descriptors: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for column in range(1, column_count):
        headers = _header_context(cells, header_rows, 0, column)
        if not headers:
            continue
        descriptor = _property_descriptor(
            table_id=table.block_id,
            column_index=column,
            headers=headers,
            caption=table.caption,
            patterns=patterns,
            direction=direction,
            table_context=table_context,
        )
        if not _descriptor_is_observation_candidate(
            descriptor,
            allow_unmapped=True,
        ):
            continue
        descriptors.append(descriptor)
        for row in range(data_start, row_count):
            condition_cell = _cell_at(cells, row, 0)
            value_cell = _cell_at(cells, row, column)
            if (
                condition_cell is None
                or value_cell is None
                or not _is_value_like_numeric(condition_cell.text)
                or not _candidate_value_like(value_cell.text)
            ):
                continue
            condition_value = _numeric_scalar(condition_cell.text)
            if condition_value is None:
                continue
            conditions = dict(descriptor["conditions"])
            conditions[condition_key] = condition_value
            item = _observation(
                table_id=table.block_id,
                cell=value_cell,
                sample_label=None,
                property_raw=descriptor["property_name_raw"],
                property_name=descriptor["property_name_normalized"],
                semantic_label=descriptor["semantic_label"],
                property_variant=descriptor["property_variant"],
                conditions=conditions,
                unit=descriptor,
                direction=direction,
            )
            if descriptor["property_name_normalized"] is not None:
                item["binding_status"] = "condition_bound"
            else:
                unresolved.append({
                    "reason": "property_mapping_not_found",
                    "cell_id": value_cell.cell_id,
                    "row_index": row,
                    "column_index": column,
                    "property_name_raw": descriptor["property_name_raw"],
                    "semantic_label": descriptor["semantic_label"],
                })
            observations.append(item)
    return descriptors, observations, unresolved


def _mixed_shadow(
    *,
    table: Stage0Element,
    cells: Sequence[Stage0TableCell],
    header_rows: set[int],
    patterns: Sequence[tuple[re.Pattern[str], str]],
    direction: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    row_count, column_count = _grid_shape(cells)
    header_row = min(header_rows, default=0)
    descriptors: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    data_start = max(header_rows, default=-1) + 1
    for sample_column in range(0, column_count - 1, 2):
        property_column = sample_column + 1
        property_header = _text(_cell_at(cells, header_row, property_column))
        if not property_header:
            continue
        semantics = _property_semantics(property_header, patterns)
        property_name = semantics["property_name_normalized"]
        unit = _unit_info([property_header], table.caption)
        descriptors.append(_property_descriptor(
            table_id=table.block_id,
            column_index=property_column,
            headers=[property_header],
            caption=table.caption,
            patterns=patterns,
            direction=direction,
        ))
        for row in range(data_start, row_count):
            sample_cell = _cell_at(cells, row, sample_column)
            value_cell = _cell_at(cells, row, property_column)
            if value_cell is None or not _is_value_like_numeric(value_cell.text):
                continue
            sample_label = _text(sample_cell) or None
            item = _observation(
                table_id=table.block_id,
                cell=value_cell,
                sample_label=sample_label,
                property_raw=property_header,
                property_name=property_name,
                semantic_label=semantics["semantic_label"],
                property_variant=semantics["property_variant"],
                conditions=semantics["conditions"],
                unit=unit,
                direction=direction,
            )
            if sample_label is None or property_name is None:
                item["binding_status"] = "unresolved"
                unresolved.append({
                    "reason": (
                        "sample_label_not_found" if sample_label is None
                        else "property_mapping_not_found"
                    ),
                    "cell_id": value_cell.cell_id,
                    "row_index": row,
                    "column_index": property_column,
                })
            observations.append(item)
    return descriptors, observations, unresolved


def shadow_extract_table(
    table: Stage0Element,
    *,
    property_patterns: Sequence[tuple[re.Pattern[str], str]] | None = None,
) -> dict[str, Any]:
    """对单张 Stage 0 表生成可审计的 Shadow 候选。"""
    cells = table_cells_for(table)
    patterns = list(property_patterns or _load_property_patterns())
    header_rows = _stage4t_header_rows(cells, patterns) if cells else set()
    solubility_caption = bool(
        re.search(r"\bsolubility\b|溶解性", table.caption or "", re.IGNORECASE)
    )
    if solubility_caption and header_rows:
        header_rows = {min(header_rows)}
    survey = survey_table(table, property_patterns=patterns)
    direction = survey["direction"]

    if direction == "column_samples":
        if solubility_caption:
            descriptors, observations, unresolved = _solubility_column_shadow(
                table=table,
                cells=cells,
                header_rows=header_rows,
                direction=direction,
            )
        else:
            column_extractor = (
                _grouped_column_shadow
                if survey.get("axis_role") == "grouped_sample"
                else _column_shadow
            )
            descriptors, observations, unresolved = column_extractor(
                table=table,
                cells=cells,
                header_rows=header_rows,
                patterns=patterns,
                direction=direction,
            )
    elif direction == "mixed":
        descriptors, observations, unresolved = _mixed_shadow(
            table=table,
            cells=cells,
            header_rows=header_rows,
            patterns=patterns,
            direction=direction,
        )
    elif direction == "row_samples":
        descriptors, observations, unresolved = _row_shadow(
            table=table,
            cells=cells,
            header_rows=header_rows,
            patterns=patterns,
            direction=direction,
        )
    elif direction == "condition_series":
        descriptors, observations, unresolved = _condition_shadow(
            table=table,
            cells=cells,
            header_rows=header_rows,
            patterns=patterns,
            direction=direction,
        )
    else:
        descriptors, observations, unresolved = [], [], []

    observations = _deduplicate_observations(observations)
    unresolved = _unresolved_for_observations(observations)

    warnings = list(survey.get("warnings") or [])
    if direction == "unknown":
        warnings.append("shadow_direction_unknown")
    if not descriptors and survey["numeric_cell_count"]:
        warnings.append("shadow_no_property_candidates")
    if unresolved:
        warnings.append("shadow_unresolved_bindings")
    if any(
        item.get("alignment_status") == "inferred_right_shift"
        for item in observations
    ):
        warnings.append("shadow_inferred_column_shift")
    return {
        "shadow_schema_version": "stage4t_table_property_shadow.v0.5",
        "shadow_version": SHADOW_VERSION,
        "candidate_layer": "broad",
        "authoritative": False,
        "table_id": table.block_id,
        "caption": table.caption,
        "direction": direction,
        "sample_axis": survey["sample_axis"],
        "axis_role": survey.get("axis_role", "unknown"),
        "header_rows": sorted(header_rows),
        "property_candidates": descriptors,
        "observations": observations,
        "unresolved": unresolved,
        "warnings": sorted(set(warnings)),
    }


def shadow_extract_document(
    document: Stage0Document | Mapping[str, Any],
) -> dict[str, Any]:
    """对一篇 Stage 0 文档的全部表格生成 Shadow 候选。"""
    if not isinstance(document, Stage0Document):
        document = Stage0Document.model_validate(document)
    tables = [
        shadow_extract_table(element)
        for element in document.elements
        if element.type == "table"
    ]
    return {
        "document_id": document.document_id,
        "table_count": len(tables),
        "tables": tables,
    }


def shadow_extract_batch(batch_root: Path) -> dict[str, Any]:
    """只读扫描批次目录，生成独立的 Stage 4T Shadow 报告。"""
    documents: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for document_dir in sorted(path for path in batch_root.iterdir() if path.is_dir()):
        stage0_path = document_dir / "stage0_blocks.json"
        if not stage0_path.is_file():
            continue
        try:
            payload = json.loads(stage0_path.read_text(encoding="utf-8"))
            documents.append(shadow_extract_document(payload))
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            failures.append({
                "document_id": document_dir.name,
                "error": f"{type(exc).__name__}: {exc}",
            })

    tables = [table for document in documents for table in document["tables"]]
    observations = [
        item for table in tables for item in table.get("observations", [])
    ]
    unresolved = [item for table in tables for item in table.get("unresolved", [])]
    direction_counts = Counter(table["direction"] for table in tables)
    binding_counts = Counter(item["binding_status"] for item in observations)
    property_counts = Counter(
        item["property_name_normalized"]
        for item in observations
        if item.get("property_name_normalized")
    )
    semantic_label_counts = Counter(
        item["semantic_label"]
        for item in observations
        if item.get("semantic_label")
    )
    property_variant_counts = Counter(
        item["property_variant"]
        for item in observations
        if item.get("property_variant")
    )
    unresolved_reason_counts = Counter(item["reason"] for item in unresolved)
    warning_counts = Counter(
        warning for table in tables for warning in table.get("warnings", [])
    )
    candidate_class_counts = Counter(
        item["candidate_class"] for item in observations
    )
    semantic_status_counts = Counter(
        item["semantic_status"] for item in observations
    )
    value_kind_counts = Counter(item["value_kind"] for item in observations)
    measurement_role_counts = Counter(
        item["measurement_role"] for item in observations
    )
    publication_status_counts = Counter(
        item["publication_gate"]["status"] for item in observations
    )
    publication_blocker_counts = Counter(
        blocker
        for item in observations
        for blocker in item["publication_gate"]["blockers"]
    )
    return {
        "shadow_schema_version": "stage4t_table_property_batch_shadow.v0.5",
        "shadow_version": SHADOW_VERSION,
        "candidate_layer": "broad",
        "authoritative": False,
        "batch_root": str(batch_root.resolve()),
        "document_count": len(documents),
        "table_count": len(tables),
        "failure_count": len(failures),
        "failures": failures,
        "summary": {
            "direction_counts": dict(sorted(direction_counts.items())),
            "observation_count": len(observations),
            "binding_status_counts": dict(sorted(binding_counts.items())),
            "candidate_class_counts": dict(sorted(candidate_class_counts.items())),
            "semantic_status_counts": dict(sorted(semantic_status_counts.items())),
            "value_kind_counts": dict(sorted(value_kind_counts.items())),
            "measurement_role_counts": dict(sorted(measurement_role_counts.items())),
            "publication_status_counts": dict(sorted(publication_status_counts.items())),
            "publication_blocker_counts": dict(sorted(publication_blocker_counts.items())),
            "unresolved_count": len(unresolved),
            "unresolved_reason_counts": dict(sorted(unresolved_reason_counts.items())),
            "property_counts": dict(sorted(property_counts.items())),
            "semantic_label_counts": dict(sorted(semantic_label_counts.items())),
            "property_variant_counts": dict(sorted(property_variant_counts.items())),
            "warning_counts": dict(sorted(warning_counts.items())),
            "tables_with_observations": sum(bool(table["observations"]) for table in tables),
        },
        "documents": documents,
    }


def render_shadow_markdown(report: Mapping[str, Any]) -> str:
    """把批次 Shadow JSON 渲染为便于逐表复核的 Markdown。"""
    summary = report.get("summary") or {}
    lines = [
        "# Stage 4T 表级性质 Shadow 报告",
        "",
        f"- Shadow 版本：`{report.get('shadow_version')}`",
        f"- 文档数：{report.get('document_count', 0)}",
        f"- 表格数：{report.get('table_count', 0)}",
        f"- 观测候选数：{summary.get('observation_count', 0)}",
        f"- 未解析绑定数：{summary.get('unresolved_count', 0)}",
        f"- 失败数：{report.get('failure_count', 0)}",
        "",
        "## 汇总",
        "",
        f"- 方向：`{summary.get('direction_counts', {})}`",
        f"- 绑定状态：`{summary.get('binding_status_counts', {})}`",
        f"- 候选类别：`{summary.get('candidate_class_counts', {})}`",
        f"- 语义状态：`{summary.get('semantic_status_counts', {})}`",
        f"- 值类型：`{summary.get('value_kind_counts', {})}`",
        f"- 测量角色：`{summary.get('measurement_role_counts', {})}`",
        f"- 发布门控：`{summary.get('publication_status_counts', {})}`",
        f"- 发布阻断原因：`{summary.get('publication_blocker_counts', {})}`",
        f"- 未解析原因：`{summary.get('unresolved_reason_counts', {})}`",
        f"- 性质分布：`{summary.get('property_counts', {})}`",
        f"- 未归一语义分布：`{summary.get('semantic_label_counts', {})}`",
        f"- 性质 variant 分布：`{summary.get('property_variant_counts', {})}`",
        f"- 警告：`{summary.get('warning_counts', {})}`",
        "",
        "## 逐表清单",
        "",
        "| 文献 | 表格 | 方向 | 性质候选 | 观测 | 已绑定 | 未解析 | 异常 |",
        "|---|---|---|---:|---:|---:|---:|---|",
    ]
    for document in report.get("documents", []):
        for table in document.get("tables", []):
            observations = table.get("observations") or []
            lines.append(
                "| {document} | {table} | {direction} | {properties} | {observations} | {bound} | {unresolved} | {warnings} |".format(
                    document=document.get("document_id"),
                    table=table.get("table_id"),
                    direction=table.get("direction"),
                    properties=len(table.get("property_candidates") or []),
                    observations=len(observations),
                    bound=sum(item.get("binding_status") == "bound" for item in observations),
                    unresolved=len(table.get("unresolved") or []),
                    warnings="、".join(table.get("warnings") or []) or "—",
                )
            )
    return "\n".join(lines) + "\n"

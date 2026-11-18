"""Stage4N/Stage4T 共用的性质语义路由。

本模块只做名称与局部上下文的安全分类，不读取或改写测量值，也不决定发布。
官方词表和 specialized 词表分别由调用方传入，避免在这里复制 Schema。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Mapping

from stages.specialized_vocabulary import SpecializedVocabulary
from stages.table_recall_audit import (
    _PROPERTY_ALIAS_PATTERNS,
    _normalized_text,
    _property_match,
)


_AMBIGUOUS_RE = re.compile(
    r"\b(?:yield|weight\s+loss|viscosity|viscometry|peak|"
    r"specific\s+gravity|temperature\s+difference)\b"
    r"|(?:^|[^a-z])(?:eta|η|δt|Δt)(?:$|[^a-z])",
    re.IGNORECASE,
)
_DENSITY_VARIANT_RE = re.compile(
    r"\b(?:graft|surface|areal|charge|segment|cross[- ]?link(?:ed)?)\s+density\b",
    re.IGNORECASE,
)
_FREE_VOLUME_RE = re.compile(
    r"\b(?:relative\s+)?free\s+volume\b|\b(?:at|near|after|before)\s+t\s*g\b",
    re.IGNORECASE,
)
_CONDUCTIVITY_VARIANT_RE = re.compile(
    r"\b(?:diffuse|electrokinetic|charge)\b",
    re.IGNORECASE,
)
_EXPLICIT_VISCOSITY_RE = re.compile(
    r"\b(?:intrinsic|inherent|reduced|specific|relative|dynamic|melt)\s+viscosity\b"
    r"|(?:eta|η)\s*(?:inh|int|red|sp|dyn|melt)\b",
    re.IGNORECASE,
)
_DYNAMIC_VISCOSITY_RE = re.compile(
    r"\b(?:dynamic|melt)\s+viscosity\b|"
    r"(?:eta|η)\s*(?:_?\s*\{?\s*(?:dyn|melt)\b)",
    re.IGNORECASE,
)
_YIELD_VARIANT_RE = re.compile(
    r"\b(?:yield\s+(?:stress|strength)|stress\s+at\s+yield)\b",
    re.IGNORECASE,
)
_SPECIFIC_GRAVITY_RE = re.compile(r"\bspecific\s+gravity\b", re.IGNORECASE)
_DENSITY_CONTEXT_RE = re.compile(
    r"\bdensit(?:y|ies)\b|"
    r"\b(?:g\s*/\s*cm\s*\^?3|kg\s*/\s*m\s*\^?3)\b|"
    r"\b(?:astm\s*)?d\s*792\b|pycnomet(?:er|ry)",
    re.IGNORECASE,
)
_DSC_RE = re.compile(r"\b(?:dsc|differential\s+scanning\s+calorimetry)\b", re.IGNORECASE)
_MELTING_CONTEXT_RE = re.compile(
    r"\b(?:melt(?:ing)?|fusion|endotherm(?:ic)?)\b|熔融|熔化|吸热",
    re.IGNORECASE,
)
_CRYSTALLIZATION_CONTEXT_RE = re.compile(
    r"\b(?:crystall(?:ization|isation)|cooling|exotherm(?:ic)?)\b|结晶|冷却|放热",
    re.IGNORECASE,
)
_GENERIC_ENTHALPY_RE = re.compile(
    r"(?:^|[^a-z])(?:\\delta|δ|Δ)\s*h(?:$|[^a-z_])|\benthalpy\b",
    re.IGNORECASE,
)
_THERMAL_CONTEXT_RE = re.compile(
    r"\b(?:tga|thermograv(?:imetric)?|thermal|decompos(?:ition|ed|ing)?)\b",
    re.IGNORECASE,
)
_MW_DISTRIBUTION_RE = re.compile(
    r"\bpdi\b|\bpolydispersity\b|\bdispersity\b|"
    r"m\s*[nw]\s*/\s*m\s*[nw]",
    re.IGNORECASE,
)
_OFFICIAL_ALIAS_PATTERNS = tuple(
    (re.compile(pattern, re.IGNORECASE), name)
    for pattern, name in _PROPERTY_ALIAS_PATTERNS
)


@lru_cache(maxsize=1)
def default_official_vocabulary() -> Mapping[str, Any]:
    """读取当前配置中的官方词表；只在 Stage4T 应用层按需调用。"""

    # 延迟导入避免 Stage4N 加载本模块时产生循环依赖。
    from stages.stage4_property import (
        DEFAULT_VOCABULARY_PATH,
        load_property_vocabulary,
    )

    return load_property_vocabulary(DEFAULT_VOCABULARY_PATH)[0]


@dataclass(frozen=True)
class SemanticResolution:
    """一个原始性质表面的安全路由结果。"""

    status: str
    official_property: str | None = None
    specialized_property_key: str | None = None
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "official_property": self.official_property,
            "specialized_property_key": self.specialized_property_key,
            "reason": self.reason,
        }


def resolve_property_surface(
    raw_name: Any,
    *,
    context: str = "",
    value_text: str = "",
    official_vocabulary: Mapping[str, Any],
    specialized_vocabulary: SpecializedVocabulary,
    stage: str,
) -> SemanticResolution:
    """按官方→specialized→歧义→范围外顺序分类性质表面。

    只有唯一且满足上下文门控的官方别名才返回 ``official``；specialized
    词表命中返回 ``specialized``。其余结果保留原始名称供审计。
    """

    raw = str(raw_name or "").strip()
    if not raw:
        return SemanticResolution("outside_vocab", reason="empty_name")
    normalized = _normalized_text(raw)
    context_only = _normalized_text(context)
    context_text = _normalized_text(f"{raw} {context}")

    # PDI/Mw/Mn 是分子量分布，不是平均分子量；当前没有可发布的独立
    # specialized 槽位，必须保留为范围外候选，不能被公式匹配误路由。
    if _MW_DISTRIBUTION_RE.search(normalized):
        return SemanticResolution(
            "outside_vocab",
            reason="molecular_weight_distribution_not_publishable",
        )

    # 这些表头需要上下文才能决定官方去向；裸写时保留 candidate，避免
    # 把组成产率、溶剂比或条件序列误认成材料性质。
    if _SPECIFIC_GRAVITY_RE.search(normalized):
        if _DENSITY_CONTEXT_RE.search(f"{context_only} {value_text}"):
            return SemanticResolution(
                "official",
                official_property="density",
                reason="specific_gravity_with_density_context",
            )
        return SemanticResolution(
            "ambiguous",
            reason="specific_gravity_requires_density_context",
        )

    if _YIELD_VARIANT_RE.search(normalized):
        mechanical_target = None
        if re.search(r"\b(?:tensile|traction)\b|拉伸|抗张", context_only, re.IGNORECASE):
            mechanical_target = "tensile_stress_at_yield"
        elif re.search(r"\b(?:shear|剪切)\b", context_only, re.IGNORECASE):
            mechanical_target = "shear_stress_at_yield"
        elif re.search(r"\b(?:flex(?:ural|ure)|bending)\b|弯曲", context_only, re.IGNORECASE):
            mechanical_target = "flexural_stress_at_yield"
        elif re.search(r"\bcompress(?:ive|ion)\b|压缩", context_only, re.IGNORECASE):
            mechanical_target = "compressive_stress_at_yield"
        if mechanical_target and mechanical_target in official_vocabulary:
            return SemanticResolution(
                "official",
                official_property=mechanical_target,
                reason="yield_variant_with_mechanical_context",
            )
        return SemanticResolution("ambiguous", reason="yield_requires_mechanical_context")

    # DSC 的 endo/exo/ΔH 只有结合熔融/结晶语境才能落到对应焓；泛写 ΔH
    # 即使带 kJ/g 也不能默认是 heat_of_fusion。
    if _DSC_RE.search(f"{context_only} {normalized}") and (
        _GENERIC_ENTHALPY_RE.search(normalized)
        or re.search(r"\b(?:endo|exo)therm(?:ic)?\b|\b(?:endo|exo)\b", normalized, re.IGNORECASE)
    ):
        if _MELTING_CONTEXT_RE.search(f"{context_only} {normalized}"):
            target = "heat_of_fusion"
        elif _CRYSTALLIZATION_CONTEXT_RE.search(f"{context_only} {normalized}"):
            target = "heat_of_crystallization"
        else:
            return SemanticResolution("ambiguous", reason="dsc_enthalpy_requires_event_context")
        if target in official_vocabulary:
            return SemanticResolution(
                "official",
                official_property=target,
                reason="dsc_enthalpy_with_event_context",
            )

    if _DYNAMIC_VISCOSITY_RE.search(normalized):
        target = (
            "melt_viscosity"
            if re.search(r"\bmelt\b|melt$", normalized, re.IGNORECASE)
            else "dynamic_viscosity"
        )
        if target in official_vocabulary:
            return SemanticResolution(
                "official",
                official_property=target,
                reason="explicit_viscosity_variant",
            )

    specialized = specialized_vocabulary.match(
        raw,
        stage=stage,
        context=context_text,
    )
    if specialized is not None:
        return SemanticResolution(
            "specialized",
            specialized_property_key=specialized.key,
            reason="specialized_vocabulary_match",
        )

    official = _property_match(
        normalized,
        _OFFICIAL_ALIAS_PATTERNS,
    ) if normalized else None
    if official in official_vocabulary:
        if official == "density" and _DENSITY_VARIANT_RE.search(normalized):
            return SemanticResolution(
                "outside_vocab",
                reason="density_variant_excluded",
            )
        if official == "glass_transition_temperature" and _FREE_VOLUME_RE.search(
            normalized
        ):
            return SemanticResolution(
                "outside_vocab",
                reason="glass_transition_variant_excluded",
            )
        if official == "electric_conductivity" and _CONDUCTIVITY_VARIANT_RE.search(
            normalized
        ) and "conduct" not in normalized:
            return SemanticResolution(
                "outside_vocab",
                reason="conductivity_variant_excluded",
            )
        if official == "intrinsic_viscosity" and not _EXPLICIT_VISCOSITY_RE.search(
            normalized
        ):
            return SemanticResolution(
                "ambiguous",
                reason="viscosity_variant_requires_context",
            )
        if official == "thermal_decomposition_weight_loss":
            value_or_context = f"{context_text} {value_text}"
            # 百分号只能说明是比例，不能区分 TGA 失重与浸泡/吸附质量变化；
            # 必须同时有热分析/分解语境，避免把普通 ``19% weight loss``
            # 错发成热分解失重档位。
            if not _THERMAL_CONTEXT_RE.search(value_or_context):
                return SemanticResolution(
                    "ambiguous",
                    reason="weight_loss_requires_thermal_context",
                )
        return SemanticResolution(
            "official",
            official_property=official,
            reason="official_alias_match",
        )

    if _AMBIGUOUS_RE.search(raw):
        return SemanticResolution(
            "ambiguous",
            reason="generic_or_variant_name",
        )
    return SemanticResolution("outside_vocab", reason="no_safe_target")

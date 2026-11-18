"""specialized 性质词表的统一 loader/matcher。

三个 Stage（4T / 4，5）与 Stage 4R 分流共用这一份契约，避免 semantic_label
再次出现「确定性代码与 LLM prompt 各写各的」分裂（见方案 §5.1/§5.2）。

匹配分两条通道：
- aliases        走转义后的**边界匹配**，禁止 `in` 子串包含，否则 `d-spacing`
                 会在 `Log d-spacing ratio` 上误命中
- header_patterns 仅用于 `2\\theta`、`\\eta_{inh}` 等公式型写法，pattern 内
                 自行容忍 LaTeX；不建通用 canonicalizer，也不改共享的
                 `_normalized_text`（那会动召回审计基线，见方案 §5.3）

全部正则在 load 时预编译并校验，配置写错立即报错。YAML 里的坏正则若不报错
会变成静默漏抽，比硬编码更难排查。
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


EXTRACTION_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VOCABULARY_PATH = EXTRACTION_ROOT / "config" / "polymer_schema.yaml"

VALID_SOURCE_FIELDS = frozenset({
    "average_molecular_weight",
    "solution_viscosity",
    "crystallinity",
    "degree_of_polymerization",
    "crystallographic_data",
    "primary_structure_informations",
    "morphology",
    "stereoregularity",
    "characteristics_of_material",
})
VALID_VALUE_KINDS = frozenset({
    "numeric_scalar",
    "numeric_multiple",
    "categorical",
    "text",
})
VALID_STAGES = frozenset({"stage4", "stage4t", "stage5"})
_REQUIRED_FIELDS = ("source_field", "value_kinds", "stages")
_KNOWN_FIELDS = frozenset({
    *_REQUIRED_FIELDS,
    "aliases",
    "header_patterns",
    "context_patterns",
    "categorical_buckets",
    "variants",
})
_KNOWN_REGISTRY_FIELDS = frozenset({
    "vocabulary_key",
    "publishable",
    "reason",
    "legacy_alias_of",
    "duplicate_of",
})


class SpecializedVocabularyError(RuntimeError):
    """词表配置无法加载或不合法。"""


class SpecializedEntry:
    """单条 specialized 性质的匹配规则。"""

    __slots__ = (
        "key",
        "source_field",
        "value_kinds",
        "stages",
        "variants",
        "categorical_buckets",
        "_alias_patterns",
        "_header_patterns",
        "_context_patterns",
    )

    def __init__(self, key: str, raw: dict[str, Any]) -> None:
        self.key = key
        self.source_field = raw["source_field"]
        self.value_kinds = tuple(raw["value_kinds"])
        self.stages = frozenset(raw["stages"])
        self.variants = tuple(raw.get("variants") or ())
        self.categorical_buckets = {
            bucket: tuple(values)
            for bucket, values in (raw.get("categorical_buckets") or {}).items()
        }
        self._alias_patterns = tuple(
            _compile(_alias_to_pattern(alias), key, "aliases")
            for alias in (raw.get("aliases") or ())
        )
        self._header_patterns = tuple(
            _compile(pattern, key, "header_patterns")
            for pattern in (raw.get("header_patterns") or ())
        )
        self._context_patterns = tuple(
            _compile(pattern, key, "context_patterns")
            for pattern in (raw.get("context_patterns") or ())
        )

    @property
    def requires_context(self) -> bool:
        return bool(self._context_patterns)

    def matches_text(self, text: str) -> bool:
        """表头/性质名是否命中 alias 边界匹配或 header pattern。"""
        if not text:
            return False
        surfaces = (text, _matching_surface(text))
        if any(
            pattern.search(surface)
            for surface in surfaces
            for pattern in (*self._alias_patterns, *self._header_patterns)
        ):
            return True
        # LaTeX/Unicode 的 M_n、M̄_w、\\overline{M}_{\\text{n}} 等写法
        # 不适合继续堆叠正则；只对 molecular_weight 做受控公式识别。
        return self.key == "molecular_weight" and _matches_molecular_weight_formula(
            surfaces[-1]
        )

    def matches_context(self, context: str) -> bool:
        """无 context_patterns 时恒真；有则要求上下文命中其中之一。"""
        if not self._context_patterns:
            return True
        if not context:
            return False
        return any(pattern.search(context) for pattern in self._context_patterns)

    def categorical_bucket_for(self, value: str) -> str | None:
        """返回受控取值所属桶名；不在闭集内返回 None。"""
        needle = (value or "").strip().casefold()
        if not needle:
            return None
        for bucket, values in self.categorical_buckets.items():
            if any(needle == item.strip().casefold() for item in values):
                return bucket
        return None


def _alias_to_pattern(alias: Any) -> str:
    if not isinstance(alias, str) or not alias.strip():
        raise SpecializedVocabularyError(f"alias 必须为非空字符串：{alias!r}")
    # 转义后做边界匹配：空格容忍连字符/下划线，两端要求非字母数字边界。
    body = r"[\s_\-]+".join(
        re.escape(part) for part in alias.strip().split()
    )
    return rf"(?<![0-9a-z]){body}(?![0-9a-z])"


_UNICODE_SUBSCRIPT_TRANSLATION = str.maketrans({
    "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4",
    "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9",
    "ₐ": "a", "ₑ": "e", "ₕ": "h", "ᵢ": "i", "ⱼ": "j",
    "ₖ": "k", "ₗ": "l", "ₘ": "m", "ₙ": "n", "ₒ": "o",
    "ₚ": "p", "ᵣ": "r", "ₛ": "s", "ₜ": "t", "ᵤ": "u",
    "ᵥ": "v", "ₓ": "x",
})


def _matching_surface(text: str) -> str:
    """投影数学/HTML 表面，供 specialized 别名匹配使用。"""

    value = html.unescape(str(text)).replace("\u00ad", "")
    # 删除常见 LaTeX 包装命令，但保留命令参数中的语义字符。
    value = re.sub(
        r"\\(?:text|mathrm|mathsf|mathbf|operatorname|overline|bar|vec|hat|tilde)\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = value.translate(_UNICODE_SUBSCRIPT_TRANSLATION)
    value = value.replace("\u0304", "")
    value = re.sub(r"[{}$\\]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _matches_molecular_weight_formula(surface: str) -> bool:
    """识别 M_n/M_w/M_v/M_z 及其 Unicode/LaTeX 包装写法。"""

    return bool(re.search(
        r"(?<![a-z])m\s*(?:[_^]\s*)?[nwvz](?![a-z])",
        surface.casefold().replace("/", " "),
    ))


def _compile(pattern: Any, key: str, field: str) -> re.Pattern[str]:
    if not isinstance(pattern, str) or not pattern.strip():
        raise SpecializedVocabularyError(
            f"{key}.{field} 含空正则：{pattern!r}"
        )
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise SpecializedVocabularyError(
            f"{key}.{field} 正则无法编译：{pattern!r}（{exc}）"
        ) from exc


@dataclass(frozen=True)
class LabelResolution:
    """一个 semantic_label 的发布去向裁决。"""

    label: str | None
    vocabulary_key: str | None
    publishable: bool
    reason: str | None
    registered: bool

    @property
    def entry_required(self) -> bool:
        return self.publishable and self.vocabulary_key is not None


class SpecializedVocabulary:
    """预编译后的词表；发布白名单即词表本身。"""

    __slots__ = ("entries", "registry", "sha256")

    def __init__(
        self,
        entries: dict[str, SpecializedEntry],
        sha256: str,
        registry: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.entries = entries
        self.sha256 = sha256
        self.registry = registry or {}

    def resolve_label(self, label: str | None) -> LabelResolution:
        """把 legacy semantic_label 解析为发布去向；4R 的唯一入口。"""
        if not label:
            return LabelResolution(
                label=None,
                vocabulary_key=None,
                publishable=False,
                reason="semantic_unmapped",
                registered=False,
            )
        record = self.registry.get(label)
        if record is None:
            return LabelResolution(
                label=label,
                vocabulary_key=None,
                publishable=False,
                reason="semantic_unmapped",
                registered=False,
            )
        key = record.get("vocabulary_key")
        publishable = bool(record.get("publishable")) and key in self.entries
        reason = None if publishable else (
            record.get("reason") or "not_in_specialized_scope"
        )
        return LabelResolution(
            label=label,
            vocabulary_key=key if publishable else None,
            publishable=publishable,
            reason=reason,
            registered=True,
        )

    def get(self, key: str | None) -> SpecializedEntry | None:
        if not key:
            return None
        return self.entries.get(key)

    def is_publishable(self, key: str | None) -> bool:
        return self.get(key) is not None

    def for_stage(self, stage: str) -> tuple[SpecializedEntry, ...]:
        return tuple(
            entry for entry in self.entries.values() if stage in entry.stages
        )

    def match(
        self,
        text: str,
        *,
        stage: str,
        context: str = "",
    ) -> SpecializedEntry | None:
        """按 stage 过滤后匹配表头文本；带 context 约束的条目优先。"""
        candidates = [
            entry
            for entry in self.for_stage(stage)
            if entry.matches_text(text) and entry.matches_context(context)
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda entry: (not entry.requires_context, entry.key))
        return candidates[0]


def _sha256_json(data: Any) -> str:
    canonical = json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_specialized_vocabulary(
    path: Path | None = None,
) -> SpecializedVocabulary:
    """读取并预编译词表；任何配置错误在此 fail-fast。"""
    target = path or DEFAULT_VOCABULARY_PATH
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8-sig")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise SpecializedVocabularyError(f"词表无效：{target}") from exc

    section = raw.get("specialized_property_vocabulary")
    if not isinstance(section, dict) or not section:
        raise SpecializedVocabularyError(
            "specialized_property_vocabulary 必须为非空对象"
        )

    entries: dict[str, SpecializedEntry] = {}
    for key, value in section.items():
        if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", key):
            raise SpecializedVocabularyError(f"词表键名非法：{key!r}")
        if not isinstance(value, dict):
            raise SpecializedVocabularyError(f"词表条目必须为对象：{key}")
        unknown = sorted(set(value) - _KNOWN_FIELDS)
        if unknown:
            raise SpecializedVocabularyError(f"{key} 含未知字段：{unknown}")
        missing = [field for field in _REQUIRED_FIELDS if field not in value]
        if missing:
            raise SpecializedVocabularyError(f"{key} 缺少必填字段：{missing}")
        if value["source_field"] not in VALID_SOURCE_FIELDS:
            raise SpecializedVocabularyError(
                f"{key}.source_field 不是 PolyInfo 九字段之一："
                f"{value['source_field']!r}"
            )
        kinds = value["value_kinds"]
        if not isinstance(kinds, list) or not kinds:
            raise SpecializedVocabularyError(f"{key}.value_kinds 必须为非空列表")
        bad_kinds = sorted(set(kinds) - VALID_VALUE_KINDS)
        if bad_kinds:
            raise SpecializedVocabularyError(f"{key}.value_kinds 非法：{bad_kinds}")
        stages = value["stages"]
        if not isinstance(stages, list) or not stages:
            raise SpecializedVocabularyError(f"{key}.stages 必须为非空列表")
        bad_stages = sorted(set(stages) - VALID_STAGES)
        if bad_stages:
            raise SpecializedVocabularyError(f"{key}.stages 非法：{bad_stages}")
        buckets = value.get("categorical_buckets")
        if buckets is not None:
            if "categorical" not in kinds:
                raise SpecializedVocabularyError(
                    f"{key} 配了 categorical_buckets 但 value_kinds 不含 categorical"
                )
            if not isinstance(buckets, dict) or not buckets:
                raise SpecializedVocabularyError(
                    f"{key}.categorical_buckets 必须为非空对象"
                )
            for bucket, values in buckets.items():
                if not isinstance(values, list) or not values:
                    raise SpecializedVocabularyError(
                        f"{key}.categorical_buckets.{bucket} 必须为非空列表"
                    )
        elif "categorical" in kinds:
            raise SpecializedVocabularyError(
                f"{key} 的 value_kinds 含 categorical，必须配 categorical_buckets"
            )
        entries[key] = SpecializedEntry(key, value)

    registry = _load_registry(raw, entries)
    return SpecializedVocabulary(entries, _sha256_json(section), registry)


def _load_registry(
    raw: dict[str, Any],
    entries: dict[str, SpecializedEntry],
) -> dict[str, dict[str, Any]]:
    """校验 semantic_label 登记表；发布白名单必须指向已编译词表条目。"""
    section = raw.get("specialized_label_registry")
    if section is None:
        return {}
    if not isinstance(section, dict) or not section:
        raise SpecializedVocabularyError(
            "specialized_label_registry 必须为非空对象"
        )
    registry: dict[str, dict[str, Any]] = {}
    for label, record in section.items():
        if not isinstance(label, str) or not re.fullmatch(
            r"[a-z][a-z0-9_]*", label
        ):
            raise SpecializedVocabularyError(f"登记表键名非法：{label!r}")
        if not isinstance(record, dict):
            raise SpecializedVocabularyError(f"登记表条目必须为对象：{label}")
        unknown = sorted(set(record) - _KNOWN_REGISTRY_FIELDS)
        if unknown:
            raise SpecializedVocabularyError(
                f"登记表 {label} 含未知字段：{unknown}"
            )
        if "publishable" not in record:
            raise SpecializedVocabularyError(
                f"登记表 {label} 缺少 publishable"
            )
        if not isinstance(record["publishable"], bool):
            raise SpecializedVocabularyError(
                f"登记表 {label}.publishable 必须为布尔值"
            )
        key = record.get("vocabulary_key")
        if record["publishable"]:
            if key not in entries:
                raise SpecializedVocabularyError(
                    f"登记表 {label} 标为可发布，但 vocabulary_key"
                    f" {key!r} 不在 specialized_property_vocabulary 中"
                )
        elif not record.get("reason"):
            raise SpecializedVocabularyError(
                f"登记表 {label} 不可发布，必须给出 reason"
            )
        registry[label] = record
    return registry


@lru_cache(maxsize=4)
def _cached(path_str: str) -> SpecializedVocabulary:
    return load_specialized_vocabulary(Path(path_str))


def get_specialized_vocabulary(
    path: Path | None = None,
) -> SpecializedVocabulary:
    """带缓存的入口；同一路径只解析编译一次。"""
    return _cached(str(path or DEFAULT_VOCABULARY_PATH))

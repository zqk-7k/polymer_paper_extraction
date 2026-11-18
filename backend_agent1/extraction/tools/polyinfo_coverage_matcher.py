# -*- coding: utf-8 -*-
"""PolyInfo coverage matcher (rebuilt 2026-08-19).

Rebuilt from the documented spec in
  testcode/batch_results/demo20_preview_final_20260812/对比报告_PolyInfo覆盖率.md  (三 / 4.2 / 10.1)
because the original ad-hoc scripts (cmp5.py / eval_stage4.py) no longer exist in the tree.

Spec implemented
----------------
* Denominator = PolyInfo points, 19 docs, reference_no_0025452 excluded.
  GT point = one entry of property[].property_item[].property_values[].
  Three docs (0033617 / 0043541 / 0043590) have no GT directory; they come from
  polyinfo数据/sample_exprot_34/sample_exprot_34.xlsx column `sample_json`.
* Prediction points are read from ALL THREE containers of final.json:
  property_observations / unresolved_property_observations / property_series[].points
* A match requires (a) same normalized property bucket AND (b) value correspondence in one
  of three tiers: exact (2% tolerance), rescaled (integer power of 10, |k| <= 6),
  reciprocal (only between electric conductivity and volume resistivity).
* Matching does NOT verify sample identity -> the result is an UPPER BOUND.
* TGA loss thresholds are compared when both sides report them. PolyInfo's
  sibling Td/weight-loss rows are also exposed as one ``paired_event_id`` for
  event-level coverage statistics; point-level counts remain unchanged.
* Explicit prediction ranges use containment/overlap tiers; ``center ± error``
  keeps its center as an exact candidate and retains the uncertainty interval.
* rescaled matches are split into `rescaled_plausible` / `rescaled_implausible` by whether the
  PREDICTED value lies inside a per-bucket physical band (see PHYS_BAND).
  credible (可信) = exact + rescaled_plausible + reciprocal_plausible.
  strict (严格)   = exact only.   loose (宽松) = every tier including implausible.

NOTE on drift: PHYS_BAND was never enumerated in the source report (only exemplified:
"thermal decomposition temperature 19C", "weight loss 286%"), so the bands below are an
explicit re-derivation. Drift versus the published 346/353 is expected and is reported
per-tier so it stays auditable.
"""
import argparse
import json
import glob
import os
import re
import unicodedata
from collections import Counter, defaultdict

EXCLUDED_DOCS = {"reference_no_0025452"}
XLSX_ONLY = {"reference_no_0033617": 33617, "reference_no_0043541": 43541, "reference_no_0043590": 43590}
SKIP_GT_FILES = {"progress_state.json", "run_manifest.json"}

# ---------------------------------------------------------------- buckets
# GT side: the 27 distinct (property_name, unit) pairs collapse onto these keys.
GT_BUCKET = {
    "thermal decomposition temperature": "td",
    "thermal decomposition weight loss": "td_wl",
    "melting temperature": "tm",
    "glass transition temperature": "tg",
    "electric conductivity": "cond",
    "volume resistivity": "resis",
    "contact angle": "contact_angle",
    "tensile stress strength at break": "tensile_strength",
    "surface tension": "surface_tension",
    "crystallization temperature": "tc",
    "tensile modulus": "tensile_modulus",
    "elongation at break": "elongation",
    "dynamic mechanical properties storage modulus": "storage_modulus",
    "dynamic flexural properties storage modulus": "storage_modulus",
    "izod impact": "izod",
    "oxygen index": "oxygen_index",
    "lc phase transition temperature": "lc_transition",
    "water absorption": "water_abs",
    "vicat softening temperature": "vicat",
    "intrinsic viscosity [eta]": "viscosity_intrinsic",
    "inherent viscosity": "viscosity_inherent",
    "reduced viscosity": "viscosity_reduced",
    "specific viscosity": "viscosity_specific",
    "heat of fusion mol conversion": "heat_fusion",
    "heat of fusion": "heat_fusion",
    "dynamic mechanical properties loss tangent": "loss_tan",
    "dynamic flexural properties loss tanget": "loss_tan",
    "dielectric loss factor": "dielectric",
    "dynamic mechanical properties loss modulus": "loss_modulus",
}

# Physical bands, applied ONLY to buckets whose unit is effectively canonical across both
# sides -- temperatures (C) and percentage-like quantities. For those, a power-of-10 slide is
# never a unit conversion, so a slid value outside the band is a genuine false match. These are
# precisely the report's own examples of implausible hits ("td 19C", "td_wl 286%").
#
# Buckets NOT listed here (moduli, strength, izod, cond, resis, viscosity_*, heat_fusion ...) have
# genuinely varying units in the literature -- MPa/GPa, J/m / kJ/m, S/cm / S/m -- which is the
# stated reason the rescaled tier exists at all (report 三 / 5.2). Banding them in one side's
# unit would misclassify legitimate conversions as implausible, so they are always plausible.
PHYS_BAND = {
    "td":               (100.0, 1200.0),
    "td_wl":            (0.0, 100.0),
    "tm":               (-50.0, 700.0),
    "tg":               (-150.0, 600.0),
    "tc":               (-50.0, 600.0),
    "lc_transition":    (-50.0, 600.0),
    "vicat":            (0.0, 500.0),
    "contact_angle":    (0.0, 180.0),
    "elongation":       (0.0, 3000.0),
    "oxygen_index":     (0.0, 100.0),
    "water_abs":        (0.0, 100.0),
    "loss_tan":         (0.0, 100.0),
}

RECIPROCAL_PAIRS = {("cond", "resis"), ("resis", "cond")}

# Prediction side: ordered rules, first match wins. Applied to lowercased name + unit.
PRED_RULES = [
    # td_wl only when the reading is NOT a temperature. "5% weight loss temperature (\u00b0C)"
    # is a td whose 5 is the paired td_wl, so the temperature guard must come first.
    ("td",               r"(weight[ _]loss|w\.?l\.?)[ _]temp|temp.{0,12}weight[ _]loss"),
    ("td_wl",            r"weight[ _]loss|mass[ _]loss|char[ _]yield|%\s*residue|residual[ _]mass|carbine[ _]residue"),
    ("td",               r"tga.{0,12}t[_ ]?\{?[id]\}?"),
    ("td",               r"thermal[ _]decomp|decomposition[ _]temp|onset of decomp|initial decomp"
                         r"|^t_?d\b|^t_?\{?d\}?(?![a-zA-Z0-9_])|t_\{?\\?\\?text\{?d|tga\s*-?\s*\d+\s*%|^t_?\d+$|t_\{?\d+\}?$"
                         r"|^t_\{?\d+\s*%\}?|t_max|t_\{?max\}?"),
    # 只有原文明确把 glass-rubber transition/process 与 alpha/a-relaxation
    # 并列为同一事件时才映射为 Tg；裸 alpha-relaxation 保持未分类。
    ("tg",               r"glass[ _\-‐‑‒–—]*(?:rubber)[ _]+(?:transition|process)[ _]+or[ _]+(?:alpha|a|α)[ _\-‐‑‒–—]*relaxation|glass[ _]transition|^tg\b|^t_?g\b|^t_?\{?g\}?(?![a-zA-Z0-9_])|t_\{?g\}?|t_\{?\\?\\?text\{?g|^tg_?\d$"),
    ("tm",               r"melting[ _]temp|melt[ _]temp|^pmt$|^t_?m\b|^t_?\{?m\}?(?![a-zA-Z0-9_])|t_\{?m\}?"
                         r"|t_\{?\\?\\?text\{?m|t_m\^g"),
    ("tc",               r"crystalli[sz]ation[ _]temp|^t_?c\b|t_\{?c\}?"),
    ("lc_transition",    r"lc[ _]phase|isotropi[sz]ation|clearing[ _]point|liquid[ _]crystal|transition_temperature_ti"),
    ("cond",             r"conductivit|\\sigma|\u03c3"),
    ("resis",            r"resistivit|volume[ _]resist"),
    ("contact_angle",    r"contact[ _]angle|water[ _]contact"),
    ("tensile_strength", r"tensile[ _](stress|strength)|yield[ _]stress|strength at break"),
    ("tensile_modulus",  r"tensile[ _]modulus|young.{0,3}s[ _]modul|compression[ _]modulus"),
    ("storage_modulus",  r"storage[ _]modulus|^e'$|e'\s*(?:/|\()|flexural[ _]modul|^modulus$"),
    ("loss_modulus",     r"loss[ _]modulus"),
    ("loss_tan",         r"loss[ _]tang|tan\s*\u03b4|tan\s*delta"),
    ("dielectric",       r"dielectric"),
    ("elongation",       r"elongation"),
    ("izod",             r"izod|impact[ _]strength|notched"),
    ("oxygen_index",     r"oxygen[ _]index|\bloi\b"),
    # A standalone gamma parameter (e.g. dielectric relaxation ``γ``) is not
    # surface energy; require surface wording or an explicit ``γ_s`` marker.
    ("surface_tension",  r"surface[ _](?:tension|energy|free[ _]energy)|(?:\\gamma|γ)(?=[^a-zA-Z]{0,12}s\b)"),
    ("water_abs",        r"water[ _](?:abs|uptake)|moisture[ _]abs"),
    ("vicat",            r"vicat"),
    # Keep the four dilute-solution viscosity quantities separate.  The order is
    # intentionally specific-to-general so eta_inh cannot fall into intrinsic.
    ("viscosity_inherent", r"inherent[ _]viscosit|\\eta_?\{?\\?\\?(text\{)?inh"
                            r"|\u03b7_?inh|\u03b7inh|\u03b7\s*(?:_\s*\{?\s*|\{\s*)inh"),
    ("viscosity_intrinsic", r"intrinsic[ _]viscosit|(?:\[\s*(?:eta|\u03b7)\s*\])"
                             r"|\\eta_?\{?\\?\\?(text\{)?int|\u03b7_?int|\u03b7int|\u03b7\s*(?:_\s*\{?\s*|\{\s*)int"),
    ("viscosity_reduced", r"reduced[ _]viscosit|\\eta_?\{?\\?\\?(text\{)?red"
                           r"|\u03b7_?red|\u03b7red|\u03b7\s*(?:_\s*\{?\s*|\{\s*)red"),
    ("viscosity_specific", r"specific[ _]viscosit|\\eta_?\{?\\?\\?(text\{)?sp"
                            r"|\u03b7_?sp|\u03b7sp|\u03b7\s*(?:_\s*\{?\s*|\{\s*)sp"),
    ("heat_fusion",      r"heat[ _]of[ _]fusion|enthalpy[ _]of[ _]fusion|\\delta h|\u0394h"),
]
PRED_RULES = [(b, re.compile(p, re.I)) for b, p in PRED_RULES]

TAG_RE = re.compile(r"<[^>]+>")

SUPERSCRIPT = {"\u2070": "0", "\u00b9": "1", "\u00b2": "2", "\u00b3": "3", "\u2074": "4",
               "\u2075": "5", "\u2076": "6", "\u2077": "7", "\u2078": "8", "\u2079": "9",
               "\u207b": "-", "\u207a": "+"}
NUM_RE = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
UNCERTAINTY_RE = re.compile(r"([-+]?\d+(?:\.\d+)?)\s*(?:±|\+/-|\\pm|plus[ -]?minus)", re.I)
RANGE_RE = re.compile(
    r"(?:\d\s*[–—-]\s*\d|\d\s+to\s+\d|between\s+\d.{0,20}\band\s+\d)",
    re.I,
)

# TGA threshold is often encoded in the property label (TGA-5%, T_{d}^{10%})
# rather than in the numeric value.  Keep this separate from ordinary percent
# parsing so a unit such as ``%`` or a residue value is never mistaken for a
# loss threshold.
TGA_THRESHOLD_PATTERNS = (
    re.compile(r"tga\s*[-_]?\s*(\d+(?:\.\d+)?)\s*\\?%", re.I),
    re.compile(r"t\s*[_-]?\s*\{?\s*d\s*\}?[^0-9]{0,24}(\d+(?:\.\d+)?)\s*\\?%", re.I),
    re.compile(r"t\s*[_-]?\s*\{?\s*(\d+(?:\.\d+)?)\s*\\?%", re.I),
    re.compile(r"(?:mass|weight)[ _-]*loss[^0-9]{0,16}(\d+(?:\.\d+)?)\s*%", re.I),
    re.compile(r"(?:loss|threshold)[ _-]*(?:percent|%)\s*[:=]?\s*(\d+(?:\.\d+)?)", re.I),
)


def _clean(s):
    s = TAG_RE.sub("", s or "")
    s = re.sub(r"\\(?:mathrm|text|mathbf|rm)\s*", "", s)
    # LaTeX commands such as ``T_{\text{g}}`` become ``T_{{g}}`` after
    # command removal; collapse only redundant brace pairs so existing
    # anchored aliases can recognize the symbol without changing content.
    previous = None
    while previous != s:
        previous = s
        s = re.sub(r"\{\{([^{}]+)\}\}", r"{\1}", s)
    return s.replace("$", " ").strip().strip(".")


def classify_surface_component(*texts):
    """Return ``polar``/``dispersive`` for an explicit surface-energy component."""
    text = " ".join(str(value or "") for value in texts)
    text = unicodedata.normalize("NFKC", text).replace("\\text", "")
    # A bare subscript/superscript such as ``T_d`` or a table footnote ``^d``
    # is not a surface-energy component. Require a gamma/surface-energy
    # context, or an explicit polar/dispersive label, before reading p/d.
    has_surface_symbol = re.search(
        r"surface\s+(?:free\s+)?energy|surface[_ ]?tension|gamma|γ", text, re.I
    )
    has_explicit_component = re.search(r"\bpolar\b|\bdispersive?\b|component[_ ]?[pd]\b", text, re.I)
    if not (has_surface_symbol or has_explicit_component):
        return None
    if re.search(r"\bpolar\b|\^\s*\{?\s*p\b|component[_ ]?p\b", text, re.I):
        return "polar"
    if re.search(r"\bdispersive?\b|\^\s*\{?\s*d\b|component[_ ]?d\b", text, re.I):
        return "dispersive"
    return None


def _numeric_scalar(value):
    """Return a finite float for a scalar-like value, otherwise None."""
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def extract_tga_threshold(*, name=None, variant=None, measurement_context=None,
                          evidence=None):
    """Extract a TGA mass-loss threshold without parsing ordinary percentages.

    Explicit condition keys are preferred.  Text fallbacks are limited to TGA/
    Td/loss-threshold patterns and table column labels, so values such as
    ``% residue at 800 C`` are not treated as a Td threshold.
    """
    contexts = []

    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                key_text = str(key).lower()
                if key_text in {
                    "mass_loss_percent", "loss_threshold_percent", "mass_loss_threshold",
                    "loss_threshold",
                }:
                    number = _numeric_scalar(item)
                    if number is not None:
                        contexts.append(number)
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)

    walk(measurement_context)
    if contexts:
        return contexts[0]

    texts = [name, variant]
    if isinstance(measurement_context, str):
        texts.append(measurement_context)

    def evidence_text(value):
        if isinstance(value, dict):
            locator = value.get("table_locator")
            if isinstance(locator, dict):
                texts.extend(locator.get(key) for key in ("column_label", "row_label"))
            texts.extend(value.get(key) for key in ("source_sentence", "text"))
            for item in value.values():
                if isinstance(item, (dict, list)):
                    evidence_text(item)
        elif isinstance(value, list):
            for item in value:
                evidence_text(item)

    evidence_text(evidence)
    for value in texts:
        if not value:
            continue
        text = unicodedata.normalize("NFKC", str(value)).replace("\\%", "%")
        text = re.sub(r"\\(?:text|mathrm)\s*", "", text)
        for pattern in TGA_THRESHOLD_PATTERNS:
            match = pattern.search(text)
            if match:
                return _numeric_scalar(match.group(1))
    return None


def extract_evidence_labels(evidence):
    """Collect table header labels from nested evidence locators."""
    labels = []

    def walk(value):
        if isinstance(value, dict):
            locator = value.get("table_locator")
            if isinstance(locator, dict) and locator.get("column_label"):
                labels.append(str(locator["column_label"]))
            for item in value.values():
                if isinstance(item, (dict, list)):
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(evidence)
    return labels


# `T_i` is genuinely ambiguous across sub-fields (report 六): TGA onset temperature vs the
# liquid-crystal isotropization/clearing point. It is resolved by DOCUMENT context, never by
# the token alone -- see LC_CONTEXT_RE, applied over all property names in the document.
TI_RE = re.compile(r"^t_?\{?i\}?\b|^t_?i\s*\(", re.I)
LC_CONTEXT_RE = re.compile(r"mesophase|nematic|smectic|hopm|liquid[ _]cryst|isotropi", re.I)


def classify_pred(name, unit, lc_context=False):
    """Try the name alone first so anchored patterns (^Tg\\d$, ^PMT$, ^E'$) can fire,
    then retry with the unit appended for names that only disambiguate via unit."""
    n = _clean(name)
    if lc_context and TI_RE.search(n):
        return "lc_transition"
    for blob in (n, (n + " " + _clean(unit)).strip()):
        if not blob:
            continue
        for bucket, pat in PRED_RULES:
            if pat.search(blob):
                return bucket
    return None


def parse_values(raw):
    """Extract candidate numeric values from a value_raw string.

    Handles Unicode superscripts, LaTeX (\\times 10^{-8}, $1 0 ^ { - 8 }$)
    and spaced-out OCR digits. Returns a list of floats.
    """
    if raw is None:
        return []
    s = unicodedata.normalize("NFKC", str(raw))
    s = "".join(SUPERSCRIPT.get(ch, ch) for ch in s)
    s = s.replace("\\times", "x").replace("\\cdot", "x").replace("\u00d7", "x")
    s = re.sub(r"\\(?:mathrm|text|mathbf|rm)\s*", "", s)
    s = s.replace("$", " ").replace("{", " ").replace("}", " ")
    s = re.sub(r"\^\s*", "^", s)
    s = re.sub(r"(?<=\d)\s+(?=\d)", "", s)
    s = re.sub(r"\^\s*\(?\s*([-+]?)\s*(\d+)\s*\)?", r"^\1\2", s)
    out = []
    for m in re.finditer(r"([-+]?\d+(?:\.\d+)?)\s*x\s*10\s*\^\s*([-+]?\d+)", s):
        try:
            out.append(float(m.group(1)) * (10.0 ** int(m.group(2))))
        except (ValueError, OverflowError):
            pass
    if out:
        return out
    for m in re.finditer(r"(?<![\d.])10\s*\^\s*([-+]?\d+)", s):
        try:
            out.append(10.0 ** int(m.group(1)))
        except (ValueError, OverflowError):
            pass
    if out:
        return out
    for m in NUM_RE.finditer(s):
        try:
            out.append(float(m.group(0)))
        except ValueError:
            pass
    return out[:4]


def classify_interval(raw, value_min=None, value_max=None):
    """Return (kind, lo, hi, center) for an explicitly expressed interval."""
    text = unicodedata.normalize("NFKC", str(raw or ""))
    uncertainty = UNCERTAINTY_RE.search(text)
    if uncertainty:
        center = _numeric_scalar(uncertainty.group(1))
        lo = _numeric_scalar(value_min)
        hi = _numeric_scalar(value_max)
        return "uncertainty", lo, hi, center
    if RANGE_RE.search(text):
        lo = _numeric_scalar(value_min)
        hi = _numeric_scalar(value_max)
        if lo is not None and hi is not None and lo != hi:
            return "range", min(lo, hi), max(lo, hi), None
    return None, None, None, None


def interval_relation(gt_lo, gt_hi, pred, bucket, pred_bucket):
    """Return a range tier when an explicit prediction interval covers GT."""
    if bucket != pred_bucket:
        return None
    p_lo = pred.get("interval_min")
    p_hi = pred.get("interval_max")
    if p_lo is None or p_hi is None or p_lo == p_hi:
        return None
    g_lo, g_hi = min(gt_lo, gt_hi), max(gt_lo, gt_hi)
    p_lo, p_hi = min(float(p_lo), float(p_hi)), max(float(p_lo), float(p_hi))
    # Range boundaries are evidence, not independent measured scalars; use a
    # small numerical tolerance here instead of the 2% scalar-value tolerance.
    tol = max(abs(g_lo), abs(g_hi), 1.0) * 1e-9
    if p_lo <= g_lo + tol and p_hi >= g_hi - tol:
        return "range_contains", 0
    if max(g_lo, p_lo) <= min(g_hi, p_hi) + tol:
        return "range_overlap", 0
    return None


def plausible(bucket, val):
    lo, hi = PHYS_BAND.get(bucket, (float("-inf"), float("inf")))
    return lo <= val <= hi


TEMPERATURE_BUCKETS = {"td", "tm", "tg", "tc", "lc_transition", "vicat"}
_CELSIUS_UNIT_RE = re.compile(r"^(?:°\s*)?c(?:elsius)?$|^deg(?:ree)?\s*°?c$", re.I)
_KELVIN_UNIT_RE = re.compile(r"^k(?:elvin)?$", re.I)
_ENERGY_PER_GRAM_RE = re.compile(r"^(?P<prefix>k)?(?P<base>cal|j)/g$", re.I)


def _temperature_unit(unit):
    """Return ``C``/``K`` only for an explicit temperature unit token.

    Property names and free-text conditions are deliberately not inspected here:
    an unlabelled value must not be converted merely because it is plausible as a
    temperature.  This keeps unit conversion auditable and prevents accidental
    conversion of quantities whose names happen to contain ``K`` or ``C``.
    """
    text = unicodedata.normalize("NFKC", str(unit or "")).strip()
    text = re.sub(r"\s+", " ", text)
    if _KELVIN_UNIT_RE.fullmatch(text):
        return "K"
    if _CELSIUS_UNIT_RE.fullmatch(text):
        return "C"
    return None


def convert_temperature_value(value, source_unit, target_unit, bucket):
    """Convert an explicitly labelled K/°C prediction to the GT unit.

    Returns ``(converted_value, operation)`` or ``(value, None)`` when the
    bucket is not temperature-like or either unit is unknown/equal.  Keeping
    this helper narrow means ordinary scale-factor matching remains unchanged.
    """
    if bucket not in TEMPERATURE_BUCKETS:
        return value, None
    source = _temperature_unit(source_unit)
    target = _temperature_unit(target_unit)
    if source is None or target is None or source == target:
        return value, None
    if source == "K" and target == "C":
        return float(value) - 273.15, "K_to_C"
    if source == "C" and target == "K":
        return float(value) + 273.15, "C_to_K"
    return value, None


def _energy_per_gram_factor(unit):
    """Return a factor to J/g for an explicit cal/J per gram unit."""
    text = unicodedata.normalize("NFKC", str(unit or "")).strip().lower()
    text = re.sub(r"\s+", "", text)
    match = _ENERGY_PER_GRAM_RE.fullmatch(text)
    if not match:
        return None
    base = match.group("base").lower()
    factor = 4.184 if base == "cal" else 1.0
    if match.group("prefix"):
        factor *= 1000.0
    return factor


def convert_heat_fusion_value(value, source_unit, target_unit, bucket):
    """Convert explicit energy-per-gram units without crossing mass/mole bases."""
    if bucket != "heat_fusion":
        return value, None
    source = _energy_per_gram_factor(source_unit)
    target = _energy_per_gram_factor(target_unit)
    if source is None or target is None or source == target:
        return value, None
    converted = float(value) * source / target
    return converted, "energy_per_g_unit_conversion"


def cmp_values(gt_lo, gt_hi, pv, bucket, pred_bucket):
    """Return (tier, scale_k) or None."""
    tol = 0.02
    lo = min(gt_lo, gt_hi)
    hi = max(gt_lo, gt_hi)
    if (lo - abs(lo) * tol) <= pv <= (hi + abs(hi) * tol):
        return "exact", 0
    if pv != 0 and not (lo == 0 and hi == 0):
        for k in range(-6, 7):
            if k == 0:
                continue
            try:
                scaled = pv * (10.0 ** k)
            except OverflowError:
                continue
            if (lo - abs(lo) * tol) <= scaled <= (hi + abs(hi) * tol):
                tier = "rescaled_plausible" if plausible(bucket, pv) else "rescaled_implausible"
                return tier, k
    if (pred_bucket, bucket) in RECIPROCAL_PAIRS and pv != 0:
        inv = 1.0 / pv
        for k in range(-6, 7):
            try:
                scaled = inv * (10.0 ** k)
            except OverflowError:
                continue
            if (lo - abs(lo) * tol) <= scaled <= (hi + abs(hi) * tol):
                tier = ("reciprocal_plausible" if plausible(pred_bucket, pv)
                        else "reciprocal_implausible")
                return tier, k
    return None


# ---------------------------------------------------------------- loaders
def load_gt(root, doc_ids):
    """-> {doc_id: [gt_point, ...]}, restricted to doc_ids (the batch's document set)."""
    gt = defaultdict(list)

    def harvest(doc_id, payload, origin):
        for pt_index, pt in enumerate(payload.get("property") or []):
            title = pt.get("property_title")
            for item_index, it in enumerate(pt.get("property_item") or []):
                values = it.get("property_values") or []
                buckets = [GT_BUCKET.get((v.get("property_name") or "").strip().lower())
                           for v in values]
                td_wl_values = [v for v, bucket in zip(values, buckets) if bucket == "td_wl"]
                td_values = [v for v, bucket in zip(values, buckets) if bucket == "td"]
                pair_id = None
                paired_mass_loss = None
                if td_values and td_wl_values:
                    pair_id = "%s:sample:%s:property:%d:item:%d" % (
                        doc_id, payload.get("sample_id") or "unknown", pt_index, item_index
                    )
                    if len(td_wl_values) == 1:
                        wl = td_wl_values[0]
                        wl_min = _numeric_scalar(wl.get("property_value_min"))
                        wl_max = _numeric_scalar(wl.get("property_value_max"))
                        if wl_min is not None and (wl_max is None or wl_min == wl_max):
                            paired_mass_loss = wl_min
                for v, bucket in zip(values, buckets):
                    name = (v.get("property_name") or "").strip()
                    row = {
                        "doc_id": doc_id,
                        "origin": origin,
                        "sample_id": payload.get("sample_id"),
                        "polymer_id": payload.get("polymer_id"),
                        "property_title": title,
                        "property_name": name,
                        "unit": v.get("property_unit"),
                        "bucket": bucket,
                        "value_min": v.get("property_value_min"),
                        "value_max": v.get("property_value_max"),
                        "measurement_condition": it.get("measurement_condition"),
                        "measurement_method": it.get("measurement_method"),
                        "coverage_eligible": True,
                        "surface_component": classify_surface_component(name, title, it.get("measurement_condition")),
                        "tga_threshold_percent": extract_tga_threshold(
                            name=name, measurement_context=it.get("measurement_condition")
                        ),
                    }
                    if pair_id:
                        row["paired_event_id"] = pair_id
                        if bucket == "td":
                            row["pair_role"] = "temperature"
                            row["paired_mass_loss_percent"] = paired_mass_loss
                            row["tga_threshold_percent"] = paired_mass_loss
                        elif bucket == "td_wl":
                            row["pair_role"] = "mass_loss"
                    gt[doc_id].append(row)

    for d in sorted(glob.glob(os.path.join(root, "polyinfo数据", "有doi", "reference_no_*"))):
        doc_id = os.path.basename(d)
        if doc_id in EXCLUDED_DOCS or doc_id not in doc_ids:
            continue
        for f in sorted(glob.glob(os.path.join(d, "*.json"))):
            if os.path.basename(f) in SKIP_GT_FILES:
                continue
            with open(f, encoding="utf-8") as fh:
                payload = json.load(fh)
            if "sample_id" not in payload:
                continue
            harvest(doc_id, payload, "gt_dir")

    import pandas as pd
    xlsx = os.path.join(root, "polyinfo数据", "sample_exprot_34", "sample_exprot_34.xlsx")
    df = pd.read_excel(xlsx)
    for doc_id, refno in XLSX_ONLY.items():
        for js in df[df["reference_no"] == refno]["sample_json"]:
            harvest(doc_id, json.loads(js), "xlsx")
    return gt


def load_gt_points(path):
    """Load versioned GT points JSONL produced by build_curated_gt_v2.py."""
    gt = defaultdict(list)

    def optional_float(value):
        if value in (None, ""):
            return None
        return float(value)

    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            row["value_min"] = optional_float(row.get("value_min"))
            row["value_max"] = optional_float(row.get("value_max"))
            row.setdefault("coverage_eligible", True)
            row.setdefault(
                "tga_threshold_percent",
                extract_tga_threshold(
                    name=row.get("property_name"),
                    measurement_context=row.get("measurement_condition"),
                ),
            )
            gt[row["doc_id"]].append(row)
    return gt


def load_pred(batch_dir):
    """-> {doc_id: [pred_point, ...]}"""
    pred = defaultdict(list)
    for d in sorted(glob.glob(os.path.join(batch_dir, "reference_no_*"))):
        doc_id = os.path.basename(d)
        if doc_id in EXCLUDED_DOCS:
            continue
        pred[doc_id] = []
        f = os.path.join(d, "final.json")
        if not os.path.exists(f):
            continue
        with open(f, encoding="utf-8") as fh:
            j = json.load(fh)

        # document-level context flag, needed to disambiguate T_i (see classify_pred)
        _names = [str(s.get("property_name_raw")) for s in (j.get("property_series") or [])]
        _names += [str(o.get("property_name_raw")) for o in (j.get("property_observations") or [])]
        lc_context = bool(LC_CONTEXT_RE.search(" ".join(_names)))

        def add(
            container,
            pid,
            name,
            unit,
            raw,
            vmin,
            vmax,
            sample_id,
            normalized_value=None,
            normalized_min=None,
            normalized_max=None,
            restored_value=None,
            measurement_context=None,
            variant=None,
            evidence=None,
        ):
            vals = []
            if normalized_min is not None:
                vals.append(float(normalized_min))
            if normalized_max is not None and (normalized_min is None or float(normalized_max) != float(normalized_min)):
                vals.append(float(normalized_max))
            if not vals and normalized_value is not None:
                vals.append(float(normalized_value))
            if not vals and restored_value is not None:
                vals.append(float(restored_value))
            if not vals and vmin is not None:
                vals.append(float(vmin))
            if vmax is not None and (vmin is None or float(vmax) != float(vmin)):
                vals.append(float(vmax))
            if not vals:
                vals = parse_values(raw)
            if not vals:
                return
            interval_kind, interval_min, interval_max, center_value = classify_interval(
                raw, vmin, vmax
            )
            if center_value is not None and all(abs(center_value - value) > 1e-12 for value in vals):
                vals.insert(0, center_value)
            evidence_name = " ".join(extract_evidence_labels(evidence))
            classification_name = " ".join(str(value or "") for value in (name, evidence_name)).strip()
            pred[doc_id].append({
                "doc_id": doc_id, "container": container, "pred_id": pid,
                "property_name_raw": name, "unit_raw": unit, "value_raw": raw,
                "sample_id": sample_id, "bucket": classify_pred(classification_name, unit, lc_context), "values": vals,
                "quantity_kind": classify_quantity_kind(classification_name),
                "surface_component": classify_surface_component(classification_name, variant),
                "evidence_header_labels": extract_evidence_labels(evidence),
                "interval_kind": interval_kind,
                "interval_min": interval_min,
                "interval_max": interval_max,
                "center_value": center_value,
                "measurement_context": measurement_context,
                "tga_threshold_percent": extract_tga_threshold(
                    name=name, variant=variant, measurement_context=measurement_context,
                    evidence=evidence,
                ),
            })

        for o in j.get("property_observations") or []:
            add("property_observations", o.get("property_id"), o.get("property_name_raw"),
                o.get("unit_normalized") or o.get("unit_raw"), o.get("value_raw"),
                o.get("value_min"), o.get("value_max"), o.get("sample_id"),
                o.get("normalized_value"), o.get("normalized_value_min"),
                o.get("normalized_value_max"), o.get("restored_value"),
                o.get("measurement_context"), o.get("variant"), o.get("evidence"))
        for o in j.get("unresolved_property_observations") or []:
            add("unresolved", o.get("unresolved_id"), o.get("property_name_raw"),
                o.get("unit_normalized") or o.get("unit_raw"), o.get("value_raw"),
                o.get("value_min"), o.get("value_max"), o.get("sample_id"),
                o.get("normalized_value"), o.get("normalized_value_min"),
                o.get("normalized_value_max"), o.get("restored_value"),
                o.get("measurement_context"), o.get("variant"), o.get("evidence"))
        for o in j.get("specialized_property_observations") or []:
            name = " ".join(
                str(o.get(key) or "")
                for key in ("semantic_label", "source_field", "variant", "property_name_raw")
                if o.get(key)
            )
            add("specialized_property_observations", o.get("specialized_id"), name,
                o.get("unit_normalized") or o.get("unit_raw"), o.get("value_raw"),
                o.get("value_min"), o.get("value_max"), o.get("sample_id"),
                o.get("normalized_value"), o.get("normalized_value_min"),
                o.get("normalized_value_max"), o.get("restored_value"),
                o.get("measurement_context"), o.get("variant"), o.get("evidence"))
        for s in j.get("property_series") or []:
            for p in s.get("points") or []:
                add("property_series", "%s/%s" % (s.get("series_id"), p.get("point_id")),
                    s.get("property_name_raw"), p.get("unit_normalized") or s.get("unit_normalized") or s.get("unit_raw"), p.get("value_raw"),
                    p.get("value_min"), p.get("value_max"), p.get("sample_id"),
                    p.get("normalized_value"), p.get("normalized_value_min"),
                    p.get("normalized_value_max"), p.get("restored_value"),
                    p.get("measurement_context") or s.get("measurement_context"),
                    s.get("variant"), p.get("evidence") or s.get("evidence"))
    return pred


def classify_quantity_kind(name):
    text = _clean(name).lower()
    if re.search(r"residual[ _]mass|residue|char[ _]yield", text):
        return "residual_mass_fraction"
    if re.search(r"weight[ _]loss|wt\.?[ _]loss", text):
        return "mass_loss_fraction"
    return None


def tga_condition_compatible(gt_point, pred_point):
    """Compare only an explicitly reported TGA loss threshold.

    PolyInfo stores the threshold as a sibling ``td_wl`` value, while Preview
    commonly stores it in ``measurement_context`` or the table header.  A
    missing threshold on either side remains compatible for backwards
    compatibility; two explicit, different thresholds are different TGA
    measurements and must not be matched merely because their temperatures
    happen to be equal.
    """
    if gt_point.get("bucket") != "td" or pred_point.get("bucket") != "td":
        return True, None
    gt_threshold = gt_point.get("tga_threshold_percent")
    if gt_threshold is None:
        gt_threshold = gt_point.get("paired_mass_loss_percent")
    pred_threshold = pred_point.get("tga_threshold_percent")
    if gt_threshold is None or pred_threshold is None:
        return True, "missing_one_side"
    try:
        same = abs(float(gt_threshold) - float(pred_threshold)) <= 0.02
    except (TypeError, ValueError):
        return True, "unparseable"
    return same, ("equal" if same else "mismatch")


def surface_component_compatible(gt_point, pred_point):
    """Do not match an explicit polar/dispersive component to total energy."""
    if gt_point.get("bucket") != "surface_tension" or pred_point.get("bucket") != "surface_tension":
        return True, None
    gt_component = gt_point.get("surface_component")
    pred_component = pred_point.get("surface_component")
    if gt_component or pred_component:
        return gt_component == pred_component, (
            "equal" if gt_component == pred_component else "mismatch"
        )
    return True, "total_or_unspecified"


TIER_ORDER = ["exact", "range_contains", "range_overlap", "rescaled_plausible", "reciprocal_plausible",
              "rescaled_implausible", "reciprocal_implausible"]
# Partial interval overlap is retained for audit/loose coverage only: it does
# not prove that the PolyInfo target value is contained in the Preview range.
CREDIBLE = {"exact", "range_contains", "rescaled_plausible", "reciprocal_plausible"}


def summarize_events(rows):
    """Collapse a PolyInfo Td/weight-loss pair to one auditable event.

    Point-level counts remain available for backwards comparison.  These event
    counts prevent a paired PolyInfo representation from looking like two
    independent extraction targets when Preview emits one Td-with-threshold.
    """
    groups = defaultdict(list)
    for index, row in enumerate(rows):
        event_id = row.get("paired_event_id") or ("row:%d" % index)
        groups[event_id].append(row)
    counts = Counter()
    for group in groups.values():
        tiers = [row.get("match_tier") for row in group if row.get("match_tier")]
        best = min(tiers, key=TIER_ORDER.index) if tiers else None
        counts["gt_events"] += 1
        if best is not None:
            counts["event_loose"] += 1
        if best in CREDIBLE:
            counts["event_credible"] += 1
        if best == "exact":
            counts["event_strict"] += 1
    return counts


def match_doc(gt_points, pred_points):
    """Per-GT-point best-tier lookup.

    Per spec 三: each GT point is asked independently ("同篇文献内同性质、数值对上即算命中"),
    so a prediction row is NOT consumed by the first GT point it satisfies. This is why the
    result is explicitly an upper bound -- sample identity is never verified.
    """
    by_gt = {}
    for gi, g in enumerate(gt_points):
        if g["bucket"] is None:
            continue
        lo, hi = g["value_min"], g["value_max"]
        if lo is None and hi is None:
            continue
        lo = hi if lo is None else lo
        hi = lo if hi is None else hi
        try:
            lo = float(lo)
            hi = float(hi)
        except (TypeError, ValueError):
            continue
        best = None
        for p in pred_points:
            if p["bucket"] is None:
                continue
            same = p["bucket"] == g["bucket"]
            recip = (p["bucket"], g["bucket"]) in RECIPROCAL_PAIRS
            thermal_mass_compatible = (
                g["bucket"] == "thermal_mass_fraction" and p["bucket"] == "td_wl"
            )
            if not (same or recip or thermal_mass_compatible):
                continue
            condition_ok, condition_match = tga_condition_compatible(g, p)
            if not condition_ok:
                continue
            component_ok, component_match = surface_component_compatible(g, p)
            if not component_ok:
                continue
            range_match = interval_relation(lo, hi, p, g["bucket"], p["bucket"])
            if range_match:
                rank = TIER_ORDER.index(range_match[0])
                range_value = p.get("center_value")
                if range_value is None:
                    range_value = (float(p["interval_min"]) + float(p["interval_max"])) / 2.0
                best = (rank, range_match[0], range_match[1], range_value, p, None,
                        condition_match, component_match)
                if rank == 0:
                    break
            scalar_values = p["values"]
            if p.get("interval_kind"):
                # Do not call an interval endpoint an exact scalar.  For an
                # uncertainty, only its reported center can be exact; for a
                # range, containment/overlap above is the appropriate tier.
                scalar_values = ([p["center_value"]]
                                 if p.get("center_value") is not None else [])
            for source_pv in scalar_values:
                pv = source_pv
                conversion = None
                converted, temperature_operation = convert_temperature_value(
                    pv, p.get("unit_raw"), g.get("unit"), g["bucket"]
                )
                if temperature_operation:
                    conversion = {
                        "operation": temperature_operation,
                        "source_unit": p.get("unit_raw"),
                        "target_unit": g.get("unit"),
                        "source_value": source_pv,
                        "converted_value": converted,
                    }
                    pv = converted
                else:
                    converted, energy_operation = convert_heat_fusion_value(
                        pv, p.get("unit_raw"), g.get("unit"), g["bucket"]
                    )
                    if energy_operation:
                        conversion = {
                            "operation": energy_operation,
                            "source_unit": p.get("unit_raw"),
                            "target_unit": g.get("unit"),
                            "source_value": source_pv,
                            "converted_value": converted,
                        }
                        pv = converted
                if thermal_mass_compatible:
                    p_kind = p.get("quantity_kind")
                    g_kind = g.get("quantity_kind")
                    if p_kind and g_kind and p_kind != g_kind:
                        pv = 100.0 - pv
                        conversion = {
                            "operation": "100_minus_x",
                            "source_quantity_kind": p_kind,
                            "target_quantity_kind": g_kind,
                            "source_value": source_pv,
                            "converted_value": pv,
                        }
                r = cmp_values(lo, hi, pv, g["bucket"], p["bucket"])
                if not r:
                    continue
                rank = TIER_ORDER.index(r[0])
                if best is None or rank < best[0]:
                    best = (rank, r[0], r[1], pv, p, conversion,
                            condition_match, component_match)
                if rank == 0:
                    break
            if best and best[0] == 0:
                break
        if best:
            by_gt[gi] = {
                "tier": best[1],
                "k": best[2],
                "pred_value": best[3],
                "pred": best[4],
                "conversion": best[5],
                "condition_match": best[6],
                "component_match": best[7],
            }
    out = []
    for gi, g in enumerate(gt_points):
        rec = dict(g)
        m = by_gt.get(gi)
        if m:
            rec["match_tier"] = m["tier"]
            rec["match_scale_k"] = m["k"]
            rec["pred_value"] = m["pred_value"]
            rec["pred_container"] = m["pred"]["container"]
            rec["pred_id"] = m["pred"]["pred_id"]
            rec["pred_name_raw"] = m["pred"]["property_name_raw"]
            rec["pred_unit_raw"] = m["pred"]["unit_raw"]
            rec["pred_sample_id"] = m["pred"]["sample_id"]
            rec["pred_evidence_header_labels"] = m["pred"].get("evidence_header_labels", [])
            rec["match_conversion"] = m["conversion"]
            rec["tga_condition_match"] = m["condition_match"]
            rec["surface_component_match"] = m["component_match"]
            rec["pred_interval_kind"] = m["pred"].get("interval_kind")
            rec["pred_interval_min"] = m["pred"].get("interval_min")
            rec["pred_interval_max"] = m["pred"].get("interval_max")
        else:
            rec["match_tier"] = None
        out.append(rec)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--batch", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default=None)
    ap.add_argument("--gt-points", default=None,
                    help="可选：版本化 GT JSONL；省略时读取原始 PolyInfo GT")
    a = ap.parse_args()

    batch_dir = a.batch if os.path.isabs(a.batch) else os.path.join(a.root, a.batch)
    pred = load_pred(batch_dir)
    gt = load_gt_points(a.gt_points) if a.gt_points else load_gt(a.root, set(pred))

    os.makedirs(a.out, exist_ok=True)
    all_rows = []
    per_doc = {}
    for doc_id in sorted(gt):
        rows = match_doc(gt[doc_id], pred.get(doc_id, []))
        all_rows.extend(rows)
        t = Counter(r["match_tier"] for r in rows)
        e = summarize_events(rows)
        per_doc[doc_id] = {
            "gt_points": len(rows),
            "gt_events": e["gt_events"],
            "pred_points": len(pred.get(doc_id, [])),
            "exact": t.get("exact", 0),
            "rescaled_plausible": t.get("rescaled_plausible", 0),
            "reciprocal_plausible": t.get("reciprocal_plausible", 0),
            "rescaled_implausible": t.get("rescaled_implausible", 0),
            "reciprocal_implausible": t.get("reciprocal_implausible", 0),
            "credible": sum(1 for r in rows if r["match_tier"] in CREDIBLE),
            "strict": t.get("exact", 0),
            "loose": sum(1 for r in rows if r["match_tier"] is not None),
            "event_credible": e["event_credible"],
            "event_strict": e["event_strict"],
            "event_loose": e["event_loose"],
        }

    by_bucket = defaultdict(lambda: {"gt": 0, "credible": 0, "strict": 0})
    for r in all_rows:
        b = r["bucket"] or "UNMAPPED"
        by_bucket[b]["gt"] += 1
        if r["match_tier"] in CREDIBLE:
            by_bucket[b]["credible"] += 1
        if r["match_tier"] == "exact":
            by_bucket[b]["strict"] += 1

    total = len(all_rows)
    event_totals = summarize_events(all_rows)
    summary = {
        "schema_version": "polyinfo_coverage.v1",
        "label": a.label or os.path.basename(batch_dir.rstrip("/\\")),
        "batch": a.batch,
        "excluded_docs": sorted(EXCLUDED_DOCS),
        "gt_points": total,
        "gt_events": event_totals["gt_events"],
        "docs": len(per_doc),
        "credible": sum(d["credible"] for d in per_doc.values()),
        "strict": sum(d["strict"] for d in per_doc.values()),
        "loose": sum(d["loose"] for d in per_doc.values()),
        "event_credible": event_totals["event_credible"],
        "event_strict": event_totals["event_strict"],
        "event_loose": event_totals["event_loose"],
        "implausible": sum(d["rescaled_implausible"] + d["reciprocal_implausible"]
                           for d in per_doc.values()),
        "per_doc": per_doc,
        "per_bucket": {k: dict(v) for k, v in sorted(by_bucket.items())},
    }
    for key in ("credible", "strict", "loose"):
        summary[key + "_rate"] = round(summary[key] / total, 4) if total else 0
    for key in ("event_credible", "event_strict", "event_loose"):
        summary[key + "_rate"] = round(summary[key] / summary["gt_events"], 4) if summary["gt_events"] else 0

    with open(os.path.join(a.out, "coverage_summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(a.out, "coverage_points.jsonl"), "w", encoding="utf-8") as fh:
        for r in all_rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    print("%-34s gt=%d credible=%d (%.2f%%) strict=%d (%.2f%%) loose=%d implausible=%d" % (
        summary["label"], total, summary["credible"], summary["credible_rate"] * 100,
        summary["strict"], summary["strict_rate"] * 100, summary["loose"], summary["implausible"]))


if __name__ == "__main__":
    main()

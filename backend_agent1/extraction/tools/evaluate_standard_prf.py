"""Reference-set PRF for article/property/value facts, ignoring sample identity.

Unlisted predictions are benchmark negatives, not confirmed extraction errors.
This tool only writes a new report; it never modifies extraction or gold data.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import html
import json
from pathlib import Path
import re

from tools.evaluate_article_standard import (
    clean, compatible, convert, numbers, pred_keys, read_standard, scaled_unit,
    semantic_value_match, source_confirmed_keys, source_standard_key, unit_key,
)


def exclusion(g):
    category = g.get('evaluation_category_v3')
    if category == '错误标准记录':
        return 'invalid_property_label'
    if (category == '条件或事件限定' and g['property_key'] == 'weight_loss'
            and g['minimum'] == g['maximum'] == 0 and unit_key(g['unit']) == '%'):
        return 'onset_is_not_measured_zero_loss'
    if category == '图内结果':
        return 'figure_numbers_outside_agreed_scope'
    return None


def gold_identity(g):
    kind = numbers(g.get('raw_value'))[1]
    scale, source_unit = scaled_unit(g.get('unit'))
    source_unit = unit_key(source_unit)
    target_unit = CANONICAL_UNITS.get(source_unit, source_unit)
    endpoints = [g['minimum'], g['maximum']]
    if all(value is not None for value in endpoints):
        endpoints, _ = convert([v * scale for v in endpoints], source_unit, target_unit)
        endpoints = tuple(format(v, '.12g') for v in endpoints)
    else:
        endpoints = tuple(endpoints)
    return (g['document_id'], source_standard_key(g), endpoints, target_unit,
            kind if kind in {'less', 'greater'} else 'numeric')


def family(key):
    if key in {'mn', 'mw', 'mz', 'mv', 'molecular_weight'}:
        return 'molecular_weight'
    if key.startswith('tensile_') and key != 'tensile_modulus':
        return 'tensile_strength'
    if key.startswith('dielectric_'):
        return 'dielectric'
    if key.startswith('viscosity_') or key == 'solution_viscosity':
        return 'solution_viscosity'
    if key.startswith('surface_tension') or key.startswith('surface_energy'):
        return 'surface_energy'
    if key in {'impact', 'izod'}:
        return 'impact'
    return key


def condition_views(p):
    """Only values already in model condition fields; never scan source prose."""
    for c in p.get('condition_context_raw', []):
        name = clean(c.get('name_raw'))
        raw = str(c.get('value_raw') or '')
        if name in {'tc', 'crystallization temperature'}:
            unit = 'K' if re.search(r'\bK\b', raw) else '°C' if re.search(r'°\s*C|celsius', raw, re.I) else None
            yield {'property_name_raw': 'crystallization temperature', 'value_raw': raw,
                   'unit_raw': unit, 'standard_property_name': None,
                   'property_subtype': None, 'view_kind': 'condition'}
        if name in {'treatment', 'aging time', 'ageing time', 'treatment time',
                    'pulse width', 'pulse repetition', 'pulse frequency'}:
            # Treatment labels contain sample/process names as well as numbers.
            # Only an explicit duration/frequency is projected to a numeric fact.
            for match in re.finditer(r'(\d+(?:\.\d+)?)\s*(days?|min(?:utes?)?|hours?|h|[μµu]s|Hz)\b', raw, re.I):
                unit = match[2].lower()
                unit = 'day' if unit.startswith('day') else 'min' if unit.startswith('min') else 'h' if unit.startswith('hour') else unit
                yield {'property_name_raw': 'treatment condition', 'value_raw': match[1],
                       'unit_raw': unit, 'standard_property_name': None,
                       'property_subtype': None, 'view_kind': 'condition'}


def observation_views(p):
    semantic = p.get('semantic_normalization', {}).get('interpretations', [])
    measurements = [v for v in semantic if v.get('relation') == 'measurement']
    fractions = [v for v in measurements if v.get('rule') in {
        'explicit_crystallinity_fraction', 'explicit_fraction_unit'}]
    # Compound phase/exp/cal fractions are decomposed by the existing explicit
    # semantic rule; their original text is not a second prediction.
    if fractions:
        base = [{**p, 'property_name_raw': v['property_name'],
                 'standard_property_name': None, 'property_subtype': None,
                 'value_raw': v['value'], 'unit_raw': v['unit'],
                 'view_kind': 'measurement'} for v in fractions]
    else:
        raw = {**p, 'view_kind': 'measurement'}
        raw['_keys'] = source_confirmed_keys(p)
        for v in measurements:
            raw['_keys'].add(next(iter(pred_keys({'property_name_raw': v['property_name']}))))
        # An explicit positive measuring frequency identifies AC, rather than
        # counting a second unspecified-dielectric fact.
        if 'dielectric_ac' in raw['_keys']:
            raw['_keys'].discard('dielectric_unspecified')
        base = [raw]
    for v in base:
        parsed, kind = numbers(v.get('value_raw'))
        if kind == 'multiple':
            for value in parsed:
                yield {**v, 'value_raw': str(value)}
        else:
            yield v
    for v in semantic:
        if v.get('relation') == 'threshold':
            yield {**p, 'property_name_raw': v['property_name'],
                   'standard_property_name': None, 'property_subtype': None,
                   'value_raw': v['value'], 'unit_raw': v['unit'],
                   'view_kind': 'threshold'}
    for v in condition_views(p):
        yield {**p, **v}


CANONICAL_UNITS = {
    'k': 'c', 'kj/m': 'j/m', 'kpa': 'pa', 'mpa': 'pa', 'gpa': 'pa',
    'kj/g': 'j/g', 'cal/g': 'j/g', 'kcal/g': 'j/g', 'angstrom': 'nm',
    'um': 'nm', 'kg/mol': 'g/mol', 's/m': 's/cm', 'ml/g': 'dl/g',
    'mn/m': 'mj/m2', 'n/m': 'mj/m2',
}


def prediction_identity(p, scoped_keys):
    keys = p.get('_keys', pred_keys(p))
    exact = keys & scoped_keys
    key = sorted(exact)[0] if exact else sorted(keys)[0]
    values, kind = numbers(p.get('value_raw'))
    scale, source_unit = scaled_unit(p.get('unit_raw'))
    source_unit = unit_key(source_unit)
    target_unit = CANONICAL_UNITS.get(source_unit, source_unit)
    converted, _ = convert([x * scale for x in values], source_unit, target_unit)
    value_key = tuple(format(x, '.12g') for x in converted) if converted else clean(p.get('value_raw'))
    return (p['document_id'], key, kind, value_key, target_unit)


def is_match(g, p):
    keys = p.get('_keys', pred_keys(p))
    relation = any(compatible(source_standard_key(g), key) for key in keys)
    return relation and semantic_value_match(g, p)[0]


def maximum_matching(edges):
    """Maximum one-to-one matching; each reference and prediction counts once."""
    assigned = {}

    def augment(gold_index, seen):
        for prediction_index in edges[gold_index]:
            if prediction_index in seen:
                continue
            seen.add(prediction_index)
            if prediction_index not in assigned or augment(assigned[prediction_index], seen):
                assigned[prediction_index] = gold_index
                return True
        return False

    for i in sorted(range(len(edges)), key=lambda j: (len(edges[j]), j)):
        augment(i, set())
    return {gold_index: prediction_index for prediction_index, gold_index in assigned.items()}


def calculate(gold, observations):
    excluded = [{**g, 'exclusion_reason': exclusion(g)} for g in gold if exclusion(g)]
    included = [g for g in gold if not exclusion(g)]
    # A unitless duplicate can share the unit of an otherwise identical numeric
    # reference only when the known-unit identity is unique. No scale is guessed.
    identities = [gold_identity(g) for g in included]
    known_units = defaultdict(set)
    known_raw_identities = defaultdict(set)
    for g, identity in zip(included, identities):
        if identity[3]:
            known_units[(identity[0], identity[1], identity[2], identity[4])].add(identity[3])
            raw_key = (identity[0], identity[1], tuple(format(v, '.12g') if v is not None else None
                       for v in (g['minimum'], g['maximum'])), identity[4])
            known_raw_identities[raw_key].add(identity)
    gold_groups = {}
    for g, identity in zip(included, identities):
        known = known_units[(identity[0], identity[1], identity[2], identity[4])]
        raw_key = (identity[0], identity[1], tuple(format(v, '.12g') if v is not None else None
                   for v in (g['minimum'], g['maximum'])), identity[4])
        if not identity[3]:
            if len(known_raw_identities[raw_key]) == 1:
                identity = next(iter(known_raw_identities[raw_key]))
            elif len(known) == 1:
                identity = (*identity[:3], next(iter(known)), identity[4])
        group = gold_groups.setdefault(identity, {'gold': g, 'gold_variants': [], 'excel_rows': []})
        group['excel_rows'].append(g['excel_row'])
        group['gold_variants'].append(g)
    groups = list(gold_groups.values())
    keys_by_doc = defaultdict(set)
    for g in included:
        keys_by_doc[g['document_id']].add(source_standard_key(g))
    prediction_groups = {}
    outside = []
    nonnumeric = []
    for p in observations:
        if p.get('extraction_status') not in {None, 'usable'}:
            continue
        for view in observation_views(p):
            keys = view.get('_keys', pred_keys(view))
            scoped_keys = keys_by_doc[view['document_id']]
            if not keys or not any(family(k) == family(s) for k in keys for s in scoped_keys):
                outside.append({'observation_id': p['observation_id'], 'view_kind': view['view_kind']})
                continue
            # Missing entries and qualitative statements are not emitted numeric
            # predictions; preserve them in a separate count rather than FP.
            if not re.search(r'\d', str(view.get('value_raw') or '')):
                nonnumeric.append({'observation_id': p['observation_id'], 'value': view.get('value_raw')})
                continue
            identity = prediction_identity(view, scoped_keys)
            group = prediction_groups.setdefault(identity, {'views': [], 'observation_ids': set()})
            group['views'].append(view)
            group['observation_ids'].add(p['observation_id'])
    predictions = list(prediction_groups.values())
    by_doc = defaultdict(list)
    for i, p in enumerate(predictions):
        by_doc[p['views'][0]['document_id']].append(i)
    edges = []
    for group in groups:
        g = group['gold']
        edges.append([i for i in by_doc[g['document_id']]
                      if any(is_match(variant, v) for variant in group['gold_variants']
                             for v in predictions[i]['views'])])
    matched = maximum_matching(edges)
    tp = len(matched)
    fp = len(predictions) - tp
    fn = len(groups) - tp
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0
    summary = {
        'schema_version': 'reference_prf.v1', 'new_model_calls': 0,
        'counting_unit': 'unique article/property/value/unit/qualifier fact; sample ignored',
        'precision_kind': 'reference_set_agreement_not_source_adjudicated_precision',
        'scope': 'reference articles and property families present in retained gold',
        'original_standard_rows': len(gold), 'excluded_rows': len(excluded),
        'exclusions': dict(Counter(x['exclusion_reason'] for x in excluded)),
        'included_standard_rows': len(included),
        'covered_standard_rows': sum(len(group['excel_rows']) for group, edge in zip(groups, edges) if edge),
        'row_recall': sum(len(group['excel_rows']) for group, edge in zip(groups, edges) if edge) / len(included),
        'unique_reference_facts': len(groups), 'unique_prediction_facts_in_scope': len(predictions),
        'true_positive_reference_pairs': tp, 'false_negative_reference_facts': fn,
        'unmatched_prediction_facts': fp, 'reference_precision': precision,
        'reference_recall': recall, 'reference_f1': f1,
        'out_of_scope_prediction_views': len(outside),
        'nonnumeric_prediction_views': len(nonnumeric),
        'gold_unique_facts_with_any_match': sum(bool(edge) for edge in edges),
        'unique_reference_facts_without_any_match': sum(not edge for edge in edges),
        'unpaired_reference_facts_with_shared_prediction': sum(bool(edges[i]) for i in range(len(groups)) if i not in matched),
        'unlisted_predictions_are_confirmed_errors': False,
        'limitations': [
            'Predictions absent from gold count as negatives only for reference-set PRF; they may be valid source facts.',
            'Reference annotations have not been proved exhaustive within each retained property family.',
            'Sample identity, component identity and measurement conditions are ignored in measurement matching.',
            'Existing explicit threshold and condition values are counted as relational facts, not as new measurements.',
            'Ambiguous property definitions/units and missing process parameters remain in the recall denominator.',
            'True extraction precision and F1 require source adjudication of unmatched predictions.',
        ],
    }
    facts = []
    for i, group in enumerate(groups):
        facts.append({'gold': group['gold'], 'excel_rows': group['excel_rows'],
                      'gold_variants': group['gold_variants'],
                      'status': 'matched' if i in matched else 'unmatched_reference',
                      'prediction_index': matched.get(i), 'candidate_prediction_indices': edges[i]})
    assigned = set(matched.values())
    prediction_details = []
    for i, group in enumerate(predictions):
        first = group['views'][0]
        prediction_details.append({'prediction_index': i,
            'status': 'matched' if i in assigned else 'unlisted_or_mismatched',
            'document_id': first['document_id'], 'property_keys': sorted(first.get('_keys', pred_keys(first))),
            'property': first['property_name_raw'], 'value': first['value_raw'], 'unit': first.get('unit_raw'),
            'view_kind': first['view_kind'], 'observation_ids': sorted(group['observation_ids'])})
    return summary, facts, prediction_details, excluded


def render(summary, gold, predictions, excluded):
    esc = lambda value: html.escape(str(value if value is not None else ''))
    s = summary
    output = ['<!doctype html><html lang="zh"><meta charset="utf-8"><title>标准集对照指标</title>',
        '<style>body{font:16px/1.6 system-ui;margin:30px;color:#203045}table{border-collapse:collapse;width:100%}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:left}input{padding:8px;width:420px}tr[hidden]{display:none}</style>',
        '<h1>标准集对照：召回率、精确率与 F1</h1>',
        f'<p>标准原有 {s["original_standard_rows"]} 行，排除 {s["excluded_rows"]} 行，保留 {s["included_standard_rows"]} 行。按行覆盖 {s["covered_standard_rows"]}/{s["included_standard_rows"]}（{s["row_recall"]:.2%}）。</p>',
        f'<p>统一按文章、性质、值、单位及比较符去重并一对一配对：标准 {s["unique_reference_facts"]} 项，范围内预测 {s["unique_prediction_facts_in_scope"]} 项，配对 {s["true_positive_reference_pairs"]} 项。</p>',
        f'<p>召回率 {s["reference_recall"]:.2%}；标准集对照精确率 {s["reference_precision"]:.2%}；标准集对照 F1 {s["reference_f1"]:.2%}。</p>',
        '<table><tr><th>指标</th><th>计算</th><th>结果</th></tr>',
        f'<tr><td>召回率</td><td>{s["true_positive_reference_pairs"]}/{s["unique_reference_facts"]}</td><td>{s["reference_recall"]:.2%}</td></tr>',
        f'<tr><td>标准集对照精确率</td><td>{s["true_positive_reference_pairs"]}/{s["unique_prediction_facts_in_scope"]}</td><td>{s["reference_precision"]:.2%}</td></tr>',
        f'<tr><td>标准集对照 F1</td><td>2×{s["true_positive_reference_pairs"]}/({s["unique_reference_facts"]}+{s["unique_prediction_facts_in_scope"]})</td><td>{s["reference_f1"]:.2%}</td></tr></table>',
        '<p><strong>精确率与 F1 是标准集一致性指标。未被标准收录的预测可能是原文中的有效信息，不能直接解释为模型误提。真实精确率需复核这些预测。</strong></p>',
        f'<p>未配对标准 {s["false_negative_reference_facts"]} 项，其中 {s["unique_reference_facts_without_any_match"]} 项没有匹配候选，{s["unpaired_reference_facts_with_shared_prediction"]} 项共享同一预测而无法重复计分。预测未获标准支持 {s["unmatched_prediction_facts"]} 项。</p>',
        '<p>只计标准文章及保留性质类别；不比较样品。已有的结晶温度条件、处理时长和失重阈值计入信息覆盖；工艺参数缺失和待裁定项继续计分。无模型调用。</p>',
        '<p><a href="summary.json">统计与口径</a> · <a href="reference_facts.jsonl">标准配对明细</a> · <a href="prediction_facts.jsonl">预测明细</a> · <a href="excluded_rows.jsonl">排除清单</a></p>',
        '<input id="q" placeholder="搜索文章、性质、值或状态">',
        '<h2>未配对的标准项</h2><table><tr><th>文章 / 标准行</th><th>性质</th><th>值 / 单位</th></tr>']
    for item in gold:
        if item['status'] == 'matched':
            continue
        g = item['gold']
        output.append(f'<tr class="item"><td>{esc(g["document_id"])} / {esc(item["excel_rows"])}</td><td>{esc(g["property"])}</td><td>{esc(g["minimum"])}–{esc(g["maximum"])} {esc(g["unit"])}</td></tr>')
    output.append('</table><h2>未获标准支持的预测（待原文复核）</h2><table><tr><th>文章 / 编号</th><th>性质 / 来源字段</th><th>值 / 单位</th></tr>')
    for p in predictions:
        if p['status'] == 'matched':
            continue
        output.append(f'<tr class="item"><td>{esc(p["document_id"])} / {p["prediction_index"]}</td><td>{esc(p["property"])} / {esc(p["view_kind"])}</td><td>{esc(p["value"])} {esc(p["unit"])}</td></tr>')
    output.append('</table><script>document.querySelector("#q").oninput=e=>document.querySelectorAll(".item").forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(e.target.value.toLowerCase()));</script></html>')
    return '\n'.join(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--standard', type=Path, required=True)
    parser.add_argument('--predictions', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError('Use a new report directory; existing reports are preserved')
    gold = read_standard(args.standard)
    observations = [json.loads(line) for line in args.predictions.read_text(encoding='utf-8').splitlines()]
    summary, facts, predictions, excluded = calculate(gold, observations)
    summary['inputs'] = {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in (args.standard, args.predictions)}
    summary['evaluation_code_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.output_dir.mkdir(parents=True)
    for name, data in [('reference_facts', facts), ('prediction_facts', predictions), ('excluded_rows', excluded)]:
        (args.output_dir / (name + '.jsonl')).write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in data), encoding='utf-8')
    (args.output_dir / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    (args.output_dir / 'report.html').write_text(render(summary, facts, predictions, excluded), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

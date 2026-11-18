"""Freeze and compare a source-found/no-index cohort; never change matches.

Review notes annotate failures only. They cannot create observations, modify
numeric values, or change capture status. Outputs are JSONL and Markdown.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

FAILURE_CLASSES = {
    'candidate_code_mismatch', 'table_cell_not_flattened',
    'value_parse_or_scale_error', 'property_condition_mismatch',
    'evidence_link_missing', 'source_not_in_current_batch', 'needs_original_review',
}


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize_observation(o):
    return {k: o.get(k) for k in (
        'source_file', 'source_collection', 'candidate_code', 'property_name_raw',
        'value_raw', 'original_value', 'original_unit', 'standard_value', 'standard_unit',
        'unit_conversion_status', 'reference_match_status', 'property_match_relation',
        'source_cell_locator', 'candidate_evidence_ids', 'index_recovery_rule',
        'index_qualifiers', 'index_semantic_evidence', 'evidence',
    ) if o.get(k) is not None}


def classify_recovery(observations):
    rules = {o.get('index_recovery_rule') for o in observations}
    if 'unflattened_decomposition_peak_cell' in rules:
        return 'table_cell_not_flattened'
    if 'explicit_source_equation_mw_mn' in rules or any(r'\sim' in str(o.get('value_raw')) for o in observations):
        return 'value_parse_or_scale_error'
    if 'frequency_header_confirms_ac' in rules:
        return 'property_condition_mismatch'
    return 'candidate_code_mismatch'


def build_diagnostics(baseline_dir: Path, current_dir: Path, output_dir: Path,
                      review_notes: Path | None = None, expected_count: int | None = None):
    baseline_path = baseline_dir / 'properties_alignment.jsonl'
    current_path = current_dir / 'properties_alignment.jsonl'
    baseline = {r['standard_record_id']: r for r in read_rows(baseline_path)}
    current = {r['standard_record_id']: r for r in read_rows(current_path)}
    if baseline.keys() != current.keys():
        raise ValueError('Baseline and current standard record sets differ')
    before_manifest = json.loads((baseline_dir / 'manifest.json').read_text(encoding='utf-8'))
    after_manifest = json.loads((current_dir / 'manifest.json').read_text(encoding='utf-8'))
    if before_manifest['standard_sha256'] != after_manifest['standard_sha256']:
        raise ValueError('The reviewed standard workbook changed')
    if Path(before_manifest['batch_dir']).resolve() != Path(after_manifest['batch_dir']).resolve():
        raise ValueError('Baseline and current batch differ')
    target_ids = {k for k, r in baseline.items() if not r['value_captured']
                  and r.get('source_review_status') == '原文数值已找到' and r.get('mapping_status') == 'mapped'}
    if expected_count is not None and len(target_ids) != expected_count:
        raise ValueError(f'Expected {expected_count} cohort records; got {len(target_ids)}')
    metadata = {r['standard_record_id']: r for r in read_rows(baseline_dir / '_standard_codes/standard_property_codes.jsonl')}
    notes = read_rows(review_notes) if review_notes else []
    if len({n['standard_record_id'] for n in notes}) != len(notes):
        raise ValueError('Duplicate review note IDs')
    for n in notes:
        if n['standard_record_id'] not in target_ids or n['index_failure_class'] not in FAILURE_CLASSES:
            raise ValueError('Invalid review note ID or failure class')
    notes = {n['standard_record_id']: n for n in notes}
    results = []
    for key in sorted(target_ids):
        now = current[key]
        matched = now.get('matched_observations') or []
        unique = {}
        for o in matched:
            compact = summarize_observation(o)
            unique[json.dumps(compact, sort_keys=True, ensure_ascii=False)] = compact
        note = notes.get(key, {}) if not matched else {}
        failure_class = classify_recovery(matched) if matched else note.get('index_failure_class', now.get('index_failure_class', 'needs_original_review'))
        result = {
            **metadata[key], 'index_failure_class': failure_class,
            'index_resolution_status': 'recovered' if matched else 'not_captured',
            'baseline_value_captured': False, 'current_value_captured': bool(matched),
            'index_failure_reason': None if matched else note.get('index_failure_reason', now.get('index_failure_reason', 'source_property_requires_review')),
            'index_diagnostic_note': note.get('index_diagnostic_note') if not matched else '真实源观测已进入索引；样品状态不阻塞性质和值出口。',
            'review_evidence': note.get('review_evidence', []),
            'index_recovery_rules': sorted({o['index_recovery_rule'] for o in matched if o.get('index_recovery_rule')}),
            'matched_source_observations': list(unique.values()),
            'matched_observation_count': len(matched), 'distinct_observation_representations': len(unique),
            'duplicate_observation_representations': len(matched)-len(unique),
            'source_locator_keys': sorted({(o.get('source_cell_locator') or {}).get('cell_id') or e
                for o in matched for e in (o.get('candidate_evidence_ids') or [])}),
        }
        results.append(result)
    old_captured = {k for k, r in baseline.items() if r['value_captured']}
    new_captured = {k for k, r in current.items() if r['value_captured']}
    regressions = sorted(old_captured-new_captured)
    recovered = sum(r['current_value_captured'] for r in results)
    output_dir.mkdir(parents=True, exist_ok=True)
    frozen = output_dir / 'baseline_111.jsonl'
    frozen_text = ''.join(json.dumps(metadata[k], ensure_ascii=False, sort_keys=True)+'\n' for k in sorted(target_ids))
    if frozen.exists():
        existing = {r['standard_record_id']: r for r in read_rows(frozen)}
        if existing != {k: metadata[k] for k in target_ids}:
            raise ValueError('Frozen baseline differs; use a new output directory')
    else:
        frozen.write_text(frozen_text, encoding='utf-8')
    for name, rows in [('diagnostics_111.jsonl', results), ('remaining_111.jsonl', [r for r in results if not r['current_value_captured']])]:
        (output_dir / name).write_text(''.join(json.dumps(r, ensure_ascii=False, sort_keys=True)+'\n' for r in rows), encoding='utf-8')
    per_property = []
    for code in sorted({r['standard_property_code'] for r in results}):
        subset = [r for r in results if r['standard_property_code'] == code]
        per_property.append({'standard_property_code': code, 'target': len(subset),
                             'recovered': sum(r['current_value_captured'] for r in subset)})
    summary = {
        'schema_version': 'source_index_diagnostics.v1',
        'baseline_dir': str(baseline_dir.resolve()), 'current_dir': str(current_dir.resolve()),
        'standard_sha256': before_manifest['standard_sha256'],
        'baseline_alignment_sha256': digest(baseline_path), 'current_alignment_sha256': digest(current_path),
        'baseline_cohort_sha256': digest(frozen), 'review_notes_sha256': digest(review_notes) if review_notes else None,
        'source_value_found_no_indexed_observation_before': len(target_ids),
        'source_value_found_no_indexed_observation_after': len(target_ids)-recovered,
        'cohort_recovered': recovered, 'before_captured': len(old_captured), 'after_captured': len(new_captured),
        'standard_records': len(current), 'capture_rate': len(new_captured)/len(current),
        'regressions': regressions, 'gains_outside_cohort': sorted((new_captured-old_captured)-target_ids),
        'failure_class_counts': dict(Counter(r['index_failure_class'] for r in results)),
        'remaining_reason_counts': dict(Counter(r['index_failure_reason'] for r in results if not r['current_value_captured'])),
        'recovered_without_source_evidence': [r['standard_record_id'] for r in results if r['current_value_captured'] and not r['source_locator_keys']],
        'per_property': per_property,
    }
    (output_dir / 'manifest.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    lines = ['# 111 条索引修复结果', '',
        f'本轮恢复 {recovered}/{len(target_ids)} 条，仍待复核 {len(target_ids)-recovered} 条。',
        f'性质和值捕获：{len(old_captured)} → {len(new_captured)} / {len(current)} = {len(new_captured)/len(current):.2%}；既有捕获回退 {len(regressions)} 条。',
        '口径：同篇论文的性质和值；样品绑定不参与。单位冲突继续保留复核。没有调用 LLM，也没有把参考值填入源观测。',
        '本轮增加原始表格漏单元格和明确公式赋值的索引入口，来源分别标记为 stage0_blocks.json/recovered_table_cells 和 equation_property_recovery；表列语义取自已有 Stage4T。', '',
        '| 性质代码 | 本轮目标 | 恢复 | 剩余 |', '|---|---:|---:|---:|']
    lines += [f'| {r["standard_property_code"]} | {r["target"]} | {r["recovered"]} | {r["target"]-r["recovered"]} |' for r in per_property]
    lines += ['', '## 剩余逐条复核', '', '| 标准记录 | 性质/参考值 | 具体原因 |', '|---|---|---|']
    for r in results:
        if not r['current_value_captured']:
            value = str(r['value_min']) if r['value_min'] == r['value_max'] else f'{r["value_min"]}–{r["value_max"]}'
            lines.append(f'| {r["standard_record_id"]} | {r["reviewed_property_name"]} / {value} | {r["index_diagnostic_note"]} |')
    lines += ['', '逐条源值、性质路由、单位转换和 evidence：`diagnostics_111.jsonl`。未恢复明细：`remaining_111.jsonl`。',
              '同一性质和值可能支持多条标准记录，重复过程观测不会增加分母；这里的覆盖率不是去重后的测量点召回率，也不代表样品匹配率。', '']
    (output_dir / 'report.md').write_text('\n'.join(lines), encoding='utf-8')
    if regressions or summary['recovered_without_source_evidence']:
        raise ValueError('Recovery regression or source evidence missing; see manifest.json')
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline-dir', type=Path, required=True)
    p.add_argument('--current-dir', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--review-notes', type=Path)
    p.add_argument('--expected-count', type=int)
    args = p.parse_args()
    result = build_diagnostics(args.baseline_dir, args.current_dir, args.output_dir, args.review_notes, args.expected_count)
    print(json.dumps({k: result[k] for k in ('cohort_recovered', 'before_captured', 'after_captured', 'regressions')}, ensure_ascii=False))


if __name__ == '__main__':
    main()

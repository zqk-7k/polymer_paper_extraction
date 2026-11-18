"""Audit configured property coverage against the actual source-first export."""
import argparse
from collections import Counter, defaultdict
import hashlib
from html import escape
import json
import os
from pathlib import Path
from urllib.parse import quote

import yaml

from stages.target_property_coverage import SECTIONS, build_catalog, build_coverage
from tools.source_extraction_export import validate_source_result


ROOT = Path(__file__).resolve().parents[1]
LABELS = {'published_present_completeness_unchecked': '已有发布，仍需查漏',
          'identified_but_not_exported': '已对应，但未进入导出',
          'candidate_needs_review': '性质或对应关系待核',
          'source_mention_needs_extraction': '正文有提及，需查是否有结果',
          'not_yet_located': '尚未定位，不能判为未报告'}


def render_report(result, summary, source_root, path):
    parts = ['<!doctype html><html lang="zh"><meta charset="utf-8"><title>目标性质逐篇对账</title>',
             '<style>body{font:15px system-ui;margin:28px;background:#f8fafc;color:#182230}table{border-collapse:collapse;width:100%;background:white}td,th{padding:9px;border:1px solid #ddd;text-align:left}th{position:sticky;top:0;background:#eaf1f8}input,select{padding:8px;margin:8px}td{overflow-wrap:anywhere;max-width:350px}</style>',
             '<h1>目标性质逐篇对账</h1>',
             f'<p>范围状态：{"待用户确认" if summary["scope_status"] == "draft" else "已确认"}。{summary["document_count"]} 篇 × {summary["target_count"]} 项性质。</p>',
             '<p>“已有发布”只表示存在对应记录；全篇是否抽全仍待查漏。“尚未定位”不等于原文未报告。本文未把外部标准答案填入结果。</p>',
             '<p>target_properties.jsonl 是本次已识别目标性质的原文交付子集；coverage.jsonl 是逐项台账；unassigned_properties.jsonl 保留尚未归类的原文性质，未擅自丢弃。</p>',
             '<input id="q" placeholder="文章编号或性质名"><select id="s"><option value="">全部状态</option>' +
             ''.join(f'<option value="{k}">{v}</option>' for k, v in LABELS.items()) + '</select>',
             '<table id="rows"><thead><tr><th>文章</th><th>目标性质</th><th>状态</th><th>已发布 / 待导出 / 待核</th><th>正文线索</th><th>来源入口</th></tr></thead><tbody>']
    for row in result['ledger']:
        source = source_root / row['document_id'] / 'report.html'
        fields = [row['document_id'], row['target_id'], LABELS[row['status']],
                  ' / '.join(str(len(row[k])) for k in ('published_observation_ids', 'unpublished_observation_ids', 'review_observation_ids')),
                  ', '.join(row['mention_block_ids']) or '尚未定位']
        parts.append('<tr data-status="' + row['status'] + '">' + ''.join('<td>' + escape(v) + '</td>' for v in fields) +
                     '<td>' + (f'<a href="{quote(Path(os.path.relpath(source, path.parent)).as_posix())}">查看原文抽取</a>' if source.is_file() else '来源见台账') + '</td></tr>')
    parts.append('</tbody></table><script>function filter(){const q=document.getElementById("q").value.toLowerCase(),s=document.getElementById("s").value;document.querySelectorAll("#rows tbody tr").forEach(r=>r.hidden=!(r.textContent.toLowerCase().includes(q)&&(!s||r.dataset.status===s)))}document.getElementById("q").oninput=filter;document.getElementById("s").onchange=filter;</script></html>')
    path.write_text('\n'.join(parts), encoding='utf-8')


def audit(source_root, export_dir, output_dir, scope_status, schema_path=ROOT / 'config/polymer_schema.yaml',
          registry_path=ROOT / 'config/standard_property_codes.v1.json', sections=SECTIONS):
    source_root, export_dir, output_dir = (Path(p).resolve() for p in (source_root, export_dir, output_dir))
    if scope_status not in {'draft', 'confirmed'}:
        raise ValueError('Scope status must be explicit')
    if output_dir.exists() or any(output_dir == p or output_dir in p.parents or p in output_dir.parents for p in (source_root, export_dir)):
        raise ValueError('Output must be a new separate directory')
    snapshots = {}

    def read(path):
        path = Path(path).resolve()
        snapshots[path] = path.read_bytes()
        return snapshots[path].decode('utf-8-sig')

    schema = yaml.safe_load(read(schema_path))
    registry = json.loads(read(registry_path))
    catalog = build_catalog(schema, registry, sections)
    documents = []
    directories = sorted(p for p in source_root.glob('reference_no_*') if p.is_dir())
    for directory in directories:
        doc = json.loads(read(directory / 'source_extraction.json'))
        validate_source_result(doc)
        if doc['document_id'] != directory.name:
            raise ValueError('Source document identity mismatch')
        documents.append(doc)
    if not documents:
        raise ValueError('No source documents')
    export_manifest = json.loads(read(export_dir / 'manifest.json'))
    if export_manifest.get('schema_version') != 'source_extraction_export.v1':
        raise ValueError('Requires a source-first export')
    published = [json.loads(line) for line in read(export_dir / 'usable_extractions.jsonl').splitlines() if line.strip()]
    if len(published) != export_manifest['counts']['usable_extractions']:
        raise ValueError('Export count mismatch')
    if export_manifest['document_count'] != len(documents):
        raise ValueError('Export document count mismatch')
    result = build_coverage(documents, catalog, published)
    by_observation = defaultdict(list)
    for assignment in result['assignments']:
        if assignment['match_status'] == 'source_property_identified' and assignment['in_usable_export']:
            by_observation[(assignment['document_id'], assignment['observation_id'])].append(assignment['target_id'])
    target_rows = [{**r, 'target_ids': sorted(by_observation[(r['document_id'], r['observation_id'])])}
                   for r in published if (r['document_id'], r['observation_id']) in by_observation]
    result['target_properties'] = target_rows
    summary = {'schema_version': 'target_property_coverage.v1', 'scope_status': scope_status,
               'document_count': len(documents), 'target_count': len(catalog['targets']),
               'document_target_pairs': len(result['ledger']),
               'status_counts': dict(Counter(r['status'] for r in result['ledger'])),
               'published_target_observations': len(target_rows),
               'unassigned_property_observations': len(result['unassigned_properties']),
               'identified_observations_missing_export': sum(len(r['unpublished_observation_ids']) for r in result['ledger']),
               'completed_pairs': 0, 'verified_absence_pairs': 0, 'goal_complete': False,
               'original_inputs_unchanged': all(p.read_bytes() == b for p, b in snapshots.items()),
               'input_hashes': {str(p): hashlib.sha256(b).hexdigest() for p, b in snapshots.items()},
               'rule_hashes': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in
                              (Path(__file__).resolve(), ROOT / 'stages/target_property_coverage.py', ROOT / 'stages/source_field_enrichment.py')},
               'api_requests': 0}
    if not summary['original_inputs_unchanged']:
        raise ValueError('Inputs changed during audit')
    output_dir.mkdir(parents=True)
    for filename, key in [('coverage', 'ledger'), ('observation_targets', 'assignments'),
                          ('unassigned_properties', 'unassigned_properties'), ('target_properties', 'target_properties')]:
        (output_dir / (filename + '.jsonl')).write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in result[key]), encoding='utf-8')
    for filename, data in [('catalog', catalog), ('summary', summary)]:
        (output_dir / (filename + '.json')).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    render_report(result, summary, source_root, output_dir / 'report.html')
    lines = ['# 目标性质逐篇对账', '', f'范围状态：{scope_status}；{len(documents)} 篇 × {len(catalog["targets"])} 项性质。', '',
             '已有发布仅表示存在记录，不表示全篇抽全；尚未定位不表示原文未报告。正文提及仅为线索，不能直接生成性质值。', '',
             '|状态|文章×性质数|', '|---|---:|']
    lines += [f'|{LABELS[k]}|{v}|' for k, v in summary['status_counts'].items()]
    lines += ['', f'已识别目标性质的交付观察：{len(target_rows)}；尚未归类的性质观察：{summary["unassigned_property_observations"]}。',
              '全篇完成项：0；已确认原文未报告项：0。原输入未改；未调用模型；旧严格发布结果未改。',
              '', '接下来按已对应未导出、对应关系待核、正文结果遗漏、尚未归类的表格性质、全文查漏的顺序处理。']
    (output_dir / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('source-root', 'export-dir', 'output-dir'):
        parser.add_argument('--' + arg, type=Path, required=True)
    parser.add_argument('--scope-status', choices=('draft', 'confirmed'), required=True)
    parser.add_argument('--sections', choices=SECTIONS, nargs='+', default=SECTIONS)
    args = parser.parse_args()
    result = audit(**vars(args))
    print(json.dumps({k: v for k, v in result.items() if not k.endswith('_hashes')}, ensure_ascii=True))


if __name__ == '__main__':
    main()

"""Export source-first observations, preserving raw cells and every legacy claim."""
from collections import Counter
from html import escape
import hashlib
import json
import os
from pathlib import Path
from tools.source_evidence_view import evidence_view
from stages.source_text_extraction import build_text_observations
from stages.source_text_reviews import reviewed_text_observations
from stages.source_figure_links import build_figure_links


def figure_file_link(raw_path, report_path, asset_roots=()):
    """Resolve only an existing image; never fabricate a location or copy images."""
    if not isinstance(raw_path,str) or not raw_path or '://' in raw_path:
        return None
    source=Path(raw_path)
    if source.suffix.lower() not in {'.png','.jpg','.jpeg','.gif','.webp','.bmp','.tif','.tiff'}:
        return None
    roots=[]
    for base in asset_roots:
        base=Path(base).resolve()
        roots.extend([base,*base.parents])
    roots.extend(Path(__file__).resolve().parents)
    candidates=[source] if source.is_absolute() else [root/source for root in dict.fromkeys(roots)]
    actual=next((p.resolve() for p in candidates if p.is_file()),None)
    if actual is None:
        return None
    try:
        href=os.path.relpath(actual,Path(report_path).resolve().parent).replace('\\','/')
    except ValueError:
        href=actual.as_uri()
    from urllib.parse import quote
    return {'resolved_image_path':str(actual),'href':quote(href,safe='/:')}


def validate_source_result(data):
    if data.get("schema_version") != "source_table_extraction.v1":
        raise ValueError("Unsupported source extraction schema")
    cells = {c["cell_id"]: c for t in data["tables"] for c in t["cells"]}
    rows = data["observations"]
    text_rows = {r['observation_id']: r for r in build_text_observations(data['document_id'], data.get('source_blocks', []))}
    text_rows.update({r['observation_id']:r for r in reviewed_text_observations(data['document_id'],data.get('source_blocks',[])+data.get('source_context_blocks',[]))[0]})
    if data.get('model_text_bundle'):
        from stages.source_model_extraction import replay_bundle
        model_rows, coverage = replay_bundle(data, data['model_text_bundle'])
        text_rows.update({r['observation_id']:r for r in model_rows})
        if coverage != data.get('model_text_coverage'):
            raise ValueError('Model coverage differs from its frozen responses')
    if len({r["observation_id"] for r in rows}) != len(rows):
        raise ValueError("Duplicate source observation")
    for row in rows:
        if row.get('source_kind') == 'text':
            if row != text_rows.get(row['observation_id']):
                raise ValueError('Text assignment differs from its preserved source spans')
            continue
        cell = cells.get(row["source_cell_id"])
        if (not cell or row["value_raw"] != cell["text"] or row["document_id"] != data["document_id"]
                or row["table_id"] != cell["table_id"] or row["value_normalized"] is not None):
            raise ValueError("Source observation differs from preserved cell")
        if any(cid not in cells for cid in row["property_header_cell_ids"] + row["sample_axis_cell_ids"]):
            raise ValueError("Unknown source axis")
        if row["property_header_path"] != [cells[cid]["text"] for cid in row["property_header_cell_ids"]]:
            raise ValueError("Source header changed")
        if any(cells[cid]['table_id']!=row['table_id'] for cid in row['property_header_cell_ids']+row['sample_axis_cell_ids']):
            raise ValueError('Source axis belongs to another table')
        if row['sample_axis_cell_ids'] and row['article_sample_label_raw'] != ' | '.join(cells[cid]['text'] for cid in row['sample_axis_cell_ids']):
            raise ValueError('Source sample label changed')
        caption_span=row.get('sample_label_caption_span')
        if caption_span:
            table=next(t for t in data['tables'] if t['table_id']==row['table_id'])
            if (table.get('caption') or '')[caption_span['start']:caption_span['end']] != row['article_sample_label_raw']:
                raise ValueError('Caption material label changed')
    if data["counts"]["observation_count"] != len(rows):
        raise ValueError("Source observation count differs")


def _derived_display(rows):
    lines = []
    for row in rows:
        relations = row.get('stage4t_relations') or {}
        subject = relations.get('subject_resolution') or {}
        if subject:
            state = {'matched': '已关联具体样品', 'entity_matched': '仅关联材料', 'ambiguous_sample': '多个样品待区分', 'unmatched_sample': '具体样品未确定'}.get(subject.get('status'), '待核对')
            lines.append('主体关联：' + state + '；' + str(subject.get('sample_id') or subject.get('entity_id') or subject.get('label') or ''))
        for relation in relations.get('scoped_relations', []):
            lines.append('限定关系：' + str(relation.get('kind')) + ' / ' + str(relation.get('source_quote')) + '；来源 ' + ', '.join(relation.get('source_refs', [])))
        if relations.get('metadata_conflicts'):
            lines.append('解释冲突：' + json.dumps(relations['metadata_conflicts'], ensure_ascii=False))
        if relations.get('alternative_candidates'):
            lines.append('同一结果另有解释候选，需核对：' + json.dumps(relations['alternative_candidates'], ensure_ascii=False))
        d = row.get('value_derivation') or {}
        sem = d.get('source_semantics') or {}
        origin = row.get('source_stage', '') + ':' + str(row.get('object_id') or '')
        values = d.get('actual_values', d.get('candidate_values'))
        if values is not None:
            state = '派生值' if d.get('status') == 'normalized' else '派生候选（待复核）'
            lines.append(f"{state}：{values} {d.get('actual_unit') or ''}；来源 {origin}")
        if d.get('scale_relation'):
            lines.append('倍率关系：' + d['scale_relation'])
        if sem.get('role_status') in {'confirmed','conflict','ambiguous'}:
            lines.append('数值角色：' + str(sem.get('source_role')) + '；' + sem['role_status'])
        for note in sem.get('footnote_associations', []):
            lines.append('脚注（' + note.get('status','') + '）：' + note.get('text_raw',''))
        for c in sem.get('conditions_from_source', []):
            lines.append('来源条件：' + json.dumps(c, ensure_ascii=False))
        context = row.get('measurement_context') or {}
        brief = {k: ({x:v for x,v in value.items() if x in {'raw','value','unit'}} if isinstance(value,dict) and k != 'other_conditions' else value)
                 for k,value in context.items() if k in {'temperature','frequency','humidity','pressure','wavelength','other_conditions'} and value}
        if brief:
            lines.append('阶段记录条件（适用范围需核对）：' + json.dumps(brief,ensure_ascii=False))
        if row.get('measurement_condition'):
            lines.append('关联测量条件：' + json.dumps(row['measurement_condition'],ensure_ascii=False))
        if d.get('warnings'):
            lines.append('待复核：' + ', '.join(d['warnings']))
        if not row.get('source_literal_verified'):
            lines.append('记录值/分量尚未与整格逐字对应；来源 ' + origin)
    return '\n'.join(dict.fromkeys(lines)) or '无派生解释；保留原值'


def _saved_interpretation_sections(data):
    bundle = data.get('source_interpretation_bundle') or {}
    parts = ['<section><h2>已保存正文解释与测量参数</h2><p>保留阶段输出及原文依据；数值定位通过不代表性质或样品绑定已验收。未关联参数保持方法级，不套用到所有样品。</p>']
    for row in bundle.get('records', []):
        if row.get('source_cell_ids'):
            continue
        quotes = [e.get('source_sentence','') for e in row.get('evidence',[]) if e.get('source_type') == 'text']
        if not quotes:
            continue
        label = ' / '.join(str(row.get(k) or '') for k in ('document_id','source_stage','object_id','property_name_raw','value_raw','unit_raw'))
        detail = ('原文数值定位已核对' if row.get('source_literal_verified') else '原文数值定位待核对') + '\n' + '\n'.join(quotes)
        parts.append('<details><summary>' + escape(label) + '</summary><p>' + escape(detail).replace('\n','<br>') + '</p></details>')
    for method in bundle.get('methods', []):
        label = ' / '.join(str(method.get(k) or '') for k in ('document_id','characterization_id','method_raw'))
        detail = {k: method.get(k) for k in ('series_id','derived_property_ids','parameters','parameter_sources','measurement_context') if method.get(k)}
        parts.append('<details><summary>' + escape(label) + '</summary><pre style="white-space:pre-wrap">' + escape(json.dumps(detail,ensure_ascii=False,indent=2)) + '</pre></details>')
    parts.append('</section>')
    return parts


def render_source_report(data, path):
    """A readable default view, with inline filtering and no hidden normalization."""
    rows = data["observations"]
    figures=data.get('figure_links')
    if figures is None:
        figures=build_figure_links(data)
    linked={}
    for index,figure in enumerate(figures):
        for oid in figure['related_observation_ids']:
            linked.setdefault(oid,[]).append((index,figure))
    status = {"usable": "可用", "needs_review": "待解释"}
    kinds = {"property": "性质", "qualitative_property": "定性性质", "context": "条件/描述", "composition": "组成", "note": "备注", "unknown": "待解释"}
    reasons = {"property_axis_requires_interpretation": "需确定性质所在的行或列", "spanning_group_row": "跨列分组说明",
               "value_spans_multiple_axes": "一个值跨越多个性质列", "value_spans_multiple_sample_rows": "一个值跨越多个样品行",
               'column_conformation_label':'构象列标签未确定',
               'inline_temperature_treatment_not_assigned':'格内温度尚未关联处理状态',
               'material_unresolved':'材料尚未确定',
               'source_location_unresolved':'来源位置尚未定位，结果已保留',
               'exact_quote_not_verified':'未核对精确引用，结果已保留',
               'model_relation_uncertain':'模型标记对应关系不确定，结果已保留',
               'material_scope_qualified':'材料范围带有例外，尚未展开为具体样品'}
    parts = ['<!doctype html><html lang="zh"><meta charset="utf-8"><title>原文抽取结果</title>',
             '<style>body{font:15px system-ui;margin:28px;color:#1d2939;background:#f8fafc}h1{font-size:26px}input,select{padding:9px;margin:8px}table{border-collapse:collapse;width:100%;background:white}td,th{padding:10px;border:1px solid #ddd;text-align:left;vertical-align:top}th{position:sticky;top:0;background:#eaf1f8}small{color:#667085}td{max-width:370px;overflow-wrap:anywhere}</style>',
             '<h1>原文抽取结果</h1><p>原值与源表或正文对应。标准化及具体样品关联是补充信息；“可用”不代表全部测量条件和标准单位已确认。复合格保持整格；正文重复提及不计为已去重测量。</p>',
             f'<p>观察记录 {len(rows)} 条；可用性质 {sum(r["extraction_status"] == "usable" and r["record_kind"] in {"property", "qualitative_property"} for r in rows)} 条。</p>',
             '<label>筛选 <input id="q" placeholder="文章、样品、性质或数值"></label><select id="s"><option value="">全部状态</option><option>可用</option><option>待解释</option></select>',
             '<table id="results"><thead><tr><th>文章 / 位置</th><th>文章代称</th><th>原文性质 / 表头</th><th>原值</th><th>单位 / 条件</th><th>状态 / 类型</th><th>补充关联</th><th>派生解释（原值不变）</th><th>原表依据</th></tr></thead><tbody>']
    for index,r in enumerate(rows):
        condition = '; '.join(f'{c["name_raw"]}: {c["value_raw"]}' for c in r["condition_context_raw"])
        fields = [r["document_id"] + '\n' + (r.get('source_locator') or r["source_cell_id"]), r["article_sample_label_raw"] or "未确定",
                  r["property_name_raw"] or "待解释", r["value_raw"], (r["unit_raw"] or r.get('unit_interpreted') or "单位未注明/待解析") + ('（符号解释）' if not r['unit_raw'] and r.get('unit_interpreted') else '') + ('；倍率待解释' if r.get('scale_source_texts') else '') + '\n' + condition,
                  status[r["extraction_status"]] + ' / ' + kinds[r["record_kind"]] + '\n' + ', '.join(reasons.get(x, x) for x in r["review_fields"] + r.get('unresolved_context_fields',[])) +
                  ('\n计算值' if r.get('result_origin')=='calculated' else '\n实验值' if r.get('result_origin')=='experimental' else '') +
                  ('\n模型抽取；基础校验，来源定位仅供核对' if r.get('citation_verification')=='best_effort' else
                   '\n模型解释；原文引用已核对' if r.get('semantic_verification')=='model_only' else ''),
                  '\n'.join([('模型分类：'+r['standard_property_name']) if r.get('standard_property_name') else '',
                             ('子类型：'+r['property_subtype']) if r.get('property_subtype') else '',
                             ('标准候选：' if r.get('standard_status')=='standard_candidate' else '')+(r.get("standard_property_code") or "标准字段未匹配"), r.get("sample_id") or ('实体：'+r['entity_id'] if r.get('entity_id') else "具体样品未关联")])]
        semantics=r.get('semantic_normalization',{})
        for v in semantics.get('interpretations',[]):
            fields[-1]+='\n规范解释：'+v['property_name']+' = '+str(v['value'])+' '+str(v.get('unit') or '')
            fields[-1]+='；依据：'+v['rule']+('；阈值条件' if v.get('relation')=='threshold' else '')
        if semantics.get('unresolved'):
            fields[-1]+='\n未归一：'+', '.join(semantics['unresolved'])
        fields.append(_derived_display(r.get('derived_interpretations', [])))
        label = '查看原句' if r.get('source_kind') == 'text' else '查看原表'
        figure_refs=''.join(f'<br><a href="#figure-{fi}">{escape(f["figure_label"] or f["figure_block_id"])}</a>' for fi,f in linked.get(r['observation_id'],[]))
        parts.append('<tr data-status="' + status[r["extraction_status"]] + '">' + ''.join('<td>' + escape(str(v)).replace('\n', '<br>') + '</td>' for v in fields) + f'<td><button type="button" data-observation="{index}">{label}</button>{figure_refs}</td></tr>')
    parts += ['</tbody></table><script>function filter(){const q=document.getElementById("q").value.toLowerCase(),s=document.getElementById("s").value;document.querySelectorAll("#results tbody tr").forEach(r=>r.hidden=!(r.textContent.toLowerCase().includes(q)&&(!s||r.dataset.status===s)))}document.getElementById("q").oninput=filter;document.getElementById("s").onchange=filter;</script>', evidence_view(data), '</html>']
    figure_html=['<section><h2>图片依据与链接</h2><p>仅定位图片和原文表述，不从图中读取数值。同段引用表示相关来源，不自动证明该图中的具体曲线对应当前样品。</p>']
    for index,figure in enumerate(figures):
        link=figure_file_link(figure['image_path'],path,figure.get('asset_roots',[]))
        label=figure['figure_label'] or figure['figure_block_id']
        button=(f'<a href="{escape(link["href"],quote=True)}" target="_blank" rel="noopener">打开原图片</a>' if link else '图片文件未定位，保留原路径')
        mentions=''.join('<details><summary>'+escape(b['block_id'])+'</summary><p>'+escape(b['text'])+'</p></details>' for b in figure['mention_blocks'])
        figure_html.append(f'<article id="figure-{index}"><h3>{escape(figure["document_id"])} / {escape(label)}</h3><p>{escape(figure["caption"])}</p><p>{button}</p>{mentions}</article>')
    figure_html.append('</section>')
    parts[-1:-1]=_saved_interpretation_sections(data) + figure_html
    Path(path).write_text('\n'.join(parts), encoding='utf-8')


def build_source_export(publication_root, output_dir):
    root, output = Path(publication_root).resolve(), Path(output_dir).resolve()
    if output.exists() or root == output or root in output.parents or output in root.parents:
        raise ValueError("Output must be a new separate directory")
    dirs = sorted(p for p in root.glob('reference_no_*') if p.is_dir())
    documents, snapshots = [], {}
    for directory in dirs:
        path = directory / 'source_extraction.json'
        if not path.is_file():
            path = directory / 'measurement_publication.json'
        if not path.is_file():
            raise ValueError("Document has no source extraction; rebuild this batch first")
        snapshots[path] = path.read_bytes()
        payload = json.loads(snapshots[path])
        data = payload if path.name == 'source_extraction.json' else payload.get('source_extraction')
        if data is None:
            raise ValueError("No source extraction; use --view standardized for historical strict exports")
        validate_source_result(data)
        from stages.source_semantic_normalization import normalize_observations
        model_rows=[r for r in data['observations'] if r.get('evidence_basis')=='model_interpretation_basic_validation']
        normalized={r['observation_id']:r for r in normalize_observations(model_rows,data)}
        data['observations']=[normalized.get(r['observation_id'],r) for r in data['observations']]
        if data['document_id'] != directory.name:
            raise ValueError("Document identity mismatch")
        documents.append(data)
    if not documents:
        raise ValueError("No source extraction documents")
    rows = [r for d in documents for r in d['observations']]
    claims = [{"document_id": d['document_id'], **c} for d in documents for c in d['claims']]
    exports = {'usable_extractions': [r for r in rows if r['extraction_status'] == 'usable'],
               'model_extractions': [r for r in rows if r.get('evidence_basis') == 'model_interpretation_basic_validation'],
               'model_text_coverage': [{'document_id':d['document_id'], **d['model_text_coverage']} for d in documents if d.get('model_text_coverage')],
               'model_review_queue': [{'document_id':d['document_id'], **issue} for d in documents for issue in d.get('model_text_coverage',{}).get('issues',[])],
               'review_extractions': [r for r in rows if r['extraction_status'] != 'usable'],
               'source_claims': claims,
               'unlocated_claims': [c for c in claims if c['disposition'] == 'source_missing_or_unlocated'],
               'source_tables': [{"document_id": d['document_id'], **t} for d in documents for t in d['tables']],
               'claim_source_traces':[{k:c.get(k) for k in ('document_id','claim_id','claim_kind','source_trace')} for c in claims],
               'source_text_blocks':[{"document_id":d['document_id'],**b} for d in documents for b in d.get('source_blocks',[])],
               'source_context_blocks':[{"document_id":d['document_id'],**b} for d in documents for b in d.get('source_context_blocks',[])]}
    exports['source_interpretation_records']=[r for d in documents for r in d.get('source_interpretation_bundle',{}).get('records',[])]
    exports['measurement_methods']=[r for d in documents for r in d.get('source_interpretation_bundle',{}).get('methods',[])]
    exports['source_figure_blocks']=[{'document_id':d['document_id'],**b} for d in documents for b in d.get('source_figure_blocks',[])]
    exports['figure_links']=[f for d in documents for f in build_figure_links(d)]
    for figure in exports['figure_links']:
        link=figure_file_link(figure['image_path'],output/'report.html',figure.get('asset_roots',[]))
        figure.update(link or {})
        figure['image_link_status']='available' if link else 'image_file_unlocated'
    if any(p.read_bytes() != content for p, content in snapshots.items()):
        raise ValueError("Inputs changed during export")
    output.mkdir(parents=True)
    for name, values in exports.items():
        (output / (name + '.jsonl')).write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in values), encoding='utf-8')
    render_source_report({'observations': rows,'tables':exports['source_tables'], 'source_blocks': exports['source_text_blocks'],
                         'source_context_blocks':exports['source_context_blocks'],
                         'figure_links':exports['figure_links'], 'source_interpretation_bundle':{'records':exports['source_interpretation_records'],'methods':exports['measurement_methods']}}, output / 'report.html')
    if exports['model_extractions']:
        render_source_report({'observations':exports['model_extractions'],'tables':exports['source_tables'],
                              'source_blocks':exports['source_text_blocks'],'source_context_blocks':exports['source_context_blocks'],
                              'figure_links':exports['figure_links']},output/'model_report.html')
    counts = {k: len(v) for k, v in exports.items()}
    counts['usable_property'] = sum(d['counts']['usable_property'] for d in documents)
    counts['available_figure_links']=sum(f['image_link_status']=='available' for f in exports['figure_links'])
    manifest = {'schema_version': 'source_extraction_export.v1', 'default_view': 'source_extraction', 'counts': counts,
                'text_review_issues':[{'document_id':d['document_id'],**issue} for d in documents for issue in d.get('text_review_issues',[])],
                'claim_trace_counts':dict(Counter(c.get('source_trace',{}).get('status','not_traced') for c in claims)),
                'record_kind_counts': dict(Counter(r['record_kind'] for r in rows)), 'document_count': len(documents),
                'input_hashes': {str(p): hashlib.sha256(v).hexdigest() for p, v in snapshots.items()},
                'original_inputs_unchanged': True, 'api_requests': 0}
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'report.md').write_text('# 原文抽取导出\n\n默认入口：report.html；可用结果：usable_extractions.jsonl。\n\n' + '\n'.join(f'- {k}: {v}' for k, v in counts.items()) + '\n\n数量按来源观察计，不等于独立标量测量或已验证准确率。原值、复合格、各阶段解释及缺少来源的声明全部保留。\n', encoding='utf-8')
    return manifest

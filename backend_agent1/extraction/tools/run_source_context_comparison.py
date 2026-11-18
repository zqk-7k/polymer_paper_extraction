"""Freeze and compare identical focal ranges with local versus full-article context.

This measures context effects on prose extraction. The deterministic table path is
identical in both arms; publication counts alone are never accuracy or recall.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import html
import json
from pathlib import Path

from llm_client import DEFAULT_CONFIG_PATH, load_pipeline_config, resolve_llm_config
from stages.sample_catalog import digest
from stages.source_model_extraction import SYSTEM_PROMPT, build_packets, compact_table
from stages.source_table_extraction import build_source_extraction
from tools.run_source_workflow import run, workflow_rule_hashes, write


def read(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def scope(packet):
    return (packet['focal_block_id'],packet['focal_start'],packet['focal_end'])


def prepare(stage0_root, output_root, documents, config_path=DEFAULT_CONFIG_PATH, asset_roots=()):
    stage0_root, output_root, config_path=map(lambda p:Path(p).resolve(),(stage0_root,output_root,config_path))
    if output_root==stage0_root or stage0_root in output_root.parents or output_root in stage0_root.parents:
        raise ValueError('Experiment must be separate from inputs')
    if not documents or len(set(documents))!=len(documents):
        raise ValueError('Select distinct documents')
    config=load_pipeline_config(config_path); resolved=resolve_llm_config(config,'stage4_property')
    schema=read_schema()
    target_ids=[s+':'+k for s in ('property_vocabulary','stage5_property_vocabulary','specialized_property_vocabulary') for k in schema[s]]
    prepared=[]; inventory=[]
    for doc in documents:
        original=stage0_root/doc/'stage0_blocks.json'
        raw=original.read_bytes(); data=build_source_extraction(json.loads(raw),include_local_reviews=False)
        if data['document_id']!=doc: raise ValueError('Document identity mismatch')
        data['source_asset_roots']=[str(Path(p).resolve()) for p in asset_roots]
        variants={m:build_packets(data,context_mode=m) for m in ('local','full_article')}
        if list(map(scope,variants['local']))!=list(map(scope,variants['full_article'])):
            raise ValueError('Comparison scopes differ')
        expected={b['block_id']:b.get('text') or '' for b in data['source_blocks']+data['source_context_blocks']}
        for packet in variants['full_article']:
            if {b['block_id']:b['text'] for b in packet['evidence_blocks']}!=expected:
                raise ValueError('Full article lost a source block')
            if [compact_table(t) for t in data['tables']] != [
                {k:v for k,v in t.items() if k not in {'page','source_block_index'}} for t in packet['related_tables']]:
                raise ValueError('Full article lost a table field')
        sizes={m:[len((SYSTEM_PROMPT+json.dumps({'target_ids':target_ids,'packet':p},ensure_ascii=False)).encode('utf8'))
                  for p in packets] for m,packets in variants.items()}
        inventory.append({'document_id':doc,'original_path':str(original),'original_sha256':hashlib.sha256(raw).hexdigest(),
            'source_fingerprint':digest(data),'focal_ranges':[list(scope(p)) for p in variants['local']],
            'packet_ids':{m:[p['packet_id'] for p in ps] for m,ps in variants.items()},
            'text_and_title_chars':sum(len(t) for t in expected.values()),'tables':len(data['tables']),
            'cells':sum(len(t['cells']) for t in data['tables']),
            'full_context_omissions':0,'request_utf8_bytes':{m:{'min':min(ns,default=0),'max':max(ns,default=0)} for m,ns in sizes.items()},
            'input_tokens':None,'token_measurement':'Obtain actual usage from server responses; bytes are not tokens.'})
        prepared.append(data)
    manifest={'schema_version':'source_context_comparison.v1','model':resolved.model,
        'config_path':str(config_path),'config_sha256':hashlib.sha256(config_path.read_bytes()).hexdigest(),
        'request_settings':{'max_tokens':int(config.get('stages',{}).get('stage4_property',{}).get('max_tokens') or 32768),
            'timeout_seconds':resolved.timeout_seconds,'thinking_effort':resolved.thinking_effort,'stream':resolved.stream},
        'system_prompt_sha256':digest(SYSTEM_PROMPT),'rules':workflow_rule_hashes(),'documents':inventory,
        'scope':'Same prose focal ranges and validator; table extraction unchanged; images reference-only.',
        'deployment_default':'local_pending_review'}
    output_root.mkdir(parents=True,exist_ok=False)
    for data in prepared:
        directory=output_root/'sources'/data['document_id']; directory.mkdir(parents=True)
        write(directory/'source_extraction.json',data)
    write(output_root/'dataset.json',manifest)
    return manifest


def read_schema():
    import yaml
    return yaml.safe_load((Path(__file__).resolve().parents[1]/'config/polymer_schema.yaml').read_text(encoding='utf8'))


def check_frozen(root):
    manifest=read(root/'dataset.json')
    if manifest['rules']!=workflow_rule_hashes() or manifest['system_prompt_sha256']!=digest(SYSTEM_PROMPT):
        raise ValueError('Workflow changed after freezing; prepare a new experiment')
    if hashlib.sha256(Path(manifest['config_path']).read_bytes()).hexdigest()!=manifest['config_sha256']:
        raise ValueError('Config changed after freezing')
    for doc in manifest['documents']:
        if digest(read(root/'sources'/doc['document_id']/'source_extraction.json'))!=doc['source_fingerprint']:
            raise ValueError('Frozen source changed')
        if hashlib.sha256(Path(doc['original_path']).read_bytes()).hexdigest()!=doc['original_sha256']:
            raise ValueError('Original source changed')
    return manifest


def execute(root, max_requests=3, workers=2, modes=('local','full_article')):
    root=Path(root).resolve(); manifest=check_frozen(root)
    if workers<1 or workers>4: raise ValueError('Use one to four request workers')
    jobs=[(d['document_id'],m) for d in sorted(manifest['documents'],key=lambda d:len(d['focal_ranges']),reverse=True) for m in modes]
    def worker(doc,mode):
        directory=root/'runs'/doc/mode
        try:
            result=run(root/'sources',directory,model=manifest['model'],documents=[doc],
                context_mode=mode,config_path=manifest['config_path'],max_requests=max_requests,
                resume=(directory/'contract.json').is_file())
            return {'document_id':doc,'mode':mode,'status':result['status'],'pending_packets':result['pending_packets']}
        except Exception as exc:
            return {'document_id':doc,'mode':mode,'status':'failed','error_type':type(exc).__name__}
    results=[]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for future in as_completed([pool.submit(worker,*job) for job in jobs]):
            result=future.result(); results.append(result)
            write(root/'execution.json',results)
    return compare(root)


def compare(root):
    root=Path(root).resolve(); manifest=check_frozen(root)
    metrics=[]; diffs=[]; paired=0; total=0
    for doc in manifest['documents']:
        docid=doc['document_id']; arms={}
        for mode in ('local','full_article'):
            directory=root/'runs'/docid/mode; rows=[]; completed=set(); responses={}; issues=[]
            summary=read(directory/'summary.json') if (directory/'summary.json').is_file() else None
            if summary:
                data=read(directory/'sources'/docid/'source_extraction.json')
                bundle=data['model_text_bundle']
                from stages.source_model_extraction import work_packets, validate_response
                for p in work_packets(data,bundle):
                    record=bundle['responses'].get(p['packet_id'])
                    if record:
                        accepted,problems,complete=validate_response(data,p,record['response'],bundle['target_ids'])
                        responses[scope(p)]=record['response']; issues.extend(problems)
                        if complete: completed.add(scope(p))
                        rows.extend((scope(p),r) for r in accepted)
                published={r['observation_id'] for line in (Path(summary['export_dir'])/'usable_extractions.jsonl').read_text(encoding='utf8').splitlines() if (r:=json.loads(line))}
            else: published=set()
            statuses=[read(p) for p in directory.glob('calls/*/*/status.json')]
            usage=[s['usage'] for s in statuses if s.get('usage') is not None]
            costs=[s['cost'] for s in statuses if s.get('cost') is not None]
            metrics.append({'document_id':docid,'mode':mode,'calls':len(statuses),
                'completed_ranges':len(completed),'planned_ranges':len(doc['focal_ranges']),
                'pending_packets':summary['pending_packets'] if summary else len(doc['focal_ranges']),
                'statuses':dict(Counter(s['status'] for s in statuses)),
                'raw_candidates':sum(len(r.get('observations',[])) for r in responses.values()),
                'validation_reasons':dict(Counter(i['reason'] for i in issues)),
                'accepted_model_rows':len(rows),'accepted_not_exported':[r['observation_id'] for _,r in rows if r['observation_id'] not in published],
                'input_tokens_reported':sum(u['input_tokens']+u.get('cache_read_input_tokens',0)+u.get('cache_creation_input_tokens',0) for u in usage),
                'max_input_tokens_reported':max((u['input_tokens']+u.get('cache_read_input_tokens',0)+u.get('cache_creation_input_tokens',0) for u in usage),default=None),
                'output_tokens_reported':sum(u['output_tokens'] for u in usage),'calls_without_usage':len(statuses)-len(usage),
                'elapsed_seconds_sum':round(sum(s.get('elapsed_seconds',0) for s in statuses),3),
                'cost_records':costs,'calls_without_cost':len(statuses)-len(costs)})
            arms[mode]=(completed,rows,responses)
        common=arms['local'][0]&arms['full_article'][0]; paired+=len(common); total+=len(doc['focal_ranges'])
        for focal in sorted(common):
            groups={m:[r for s,r in arm[1] if s==focal] for m,arm in arms.items()}
            # Source identities include material and conditions: changed bindings remain visible.
            raw={m:arm[2].get(focal) for m,arm in arms.items()}
            if ({r['observation_id'] for r in groups['local']}!={r['observation_id'] for r in groups['full_article']}
                    or raw['local']!=raw['full_article']):
                diffs.append({'document_id':docid,'focal_range':list(focal),'arms':groups,
                    'raw_responses':raw,
                    'review_status':'pending','source_path':str(root/'sources'/docid/'source_extraction.json')})
    result={'model':manifest['model'],'paired_completed_ranges':paired,'planned_ranges_per_arm':total,
        'execution_complete':all(m['pending_packets']==0 for m in metrics), 'metrics':metrics,
        'different_focal_ranges':len(diffs),'quality_review_complete':False,'accuracy':None,'recall':None,
        'default_decision':'Retain local default until paired differences and omissions are reviewed.',
        'limitations':['Byte counts are not token counts; successful requests only verify observed sizes.',
            'Model rows with exact citations are not independently verified measurements.',
            'This comparison does not evaluate a new table extraction model or image values.']}
    write(root/'comparison.json',result)
    write(root/'differences.json',diffs)
    lines=['# 完整上下文对照试验','',f'已完成配对范围：{paired}/{total}；存在结果差异的范围：{len(diffs)}。',
        '','两组使用同一模型、提示词、逐段抽取范围和校验。表格抽取不变，图片只定位和挂链接。',
        '','|文章|上下文|已完成范围|调用|通过引用校验的模型记录|输入 token（已报告部分）|缺少用量的调用|',
        '|---|---|---:|---:|---:|---:|---:|']
    for m in metrics:
        lines.append(f"|{m['document_id']}|{m['mode']}|{m['completed_ranges']}/{m['planned_ranges']}|{m['calls']}|{m['accepted_model_rows']}|{m['input_tokens_reported']}|{m['calls_without_usage']}|")
    lines+=['','差异保存在 differences.json，可沿 source_path 核对原文，runs 下保存请求、原始响应、校验与导出。',
        '','尚未据此宣布准确率或召回率提高；保留原批处理默认方式，完整上下文可通过参数启用。']
    (root/'comparison.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    render_review(root,diffs,result)
    return result


def render_review(root, diffs, result):
    """A review surface, not automatic semantic acceptance of model suggestions."""
    esc=lambda value:html.escape(str(value) if value is not None else '')
    def quote(value):
        return value.get('quote','') if isinstance(value,dict) else value
    reason_labels={
        'missing_source_citation':'引用字段格式不完整',
        'source_quote_missing_or_ambiguous':'引用文字找不到或重复，无法唯一定位',
        'citation_outside_request':'引用位置不在本次可用证据中',
        'value_outside_focal_range':'引用超出本段抽取范围',
        'comparison_without_concrete_value':'只有比较描述，没有明确性质值',
        'relation_not_reported':'未明确确认原文中的对应关系',
        'invalid_condition_name':'条件名称缺失',
        'malformed_observation':'记录结构不完整',
        'unknown_target_preserved_as_raw':'目录未识别，已保留原文结果'}
    parts=['<!doctype html><meta charset="utf-8"><title>完整文章上下文对照</title>',
        '<style>body{font:16px/1.6 system-ui;margin:28px;max-width:1600px;color:#172432}article{border-top:2px solid #bbcbd9;margin-top:32px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6f8;padding:16px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #d7e0e8;padding:8px;vertical-align:top}td{overflow-wrap:anywhere}.arms{display:grid;grid-template-columns:1fr 1fr;gap:20px}.bad{color:#a32929}.ok{color:#19633c}@media(max-width:900px){.arms{grid-template-columns:1fr}}</style>',
        '<h1>完整文章上下文对照</h1>',
        f"<p>配对范围 {result['paired_completed_ranges']} / {result['planned_ranges_per_arm']}；存在原始响应或导出记录差异的范围 {len(diffs)}。</p>",
        '<p>通过引用校验只说明能定位原文，不等于材料绑定、单位或科学含义已经人工确认。本轮表格抽取保持相同，图片只定位和挂链接。</p>',
        '<p><a href="comparison.md">统计报告</a> · <a href="differences.json">完整差异数据</a></p>']
    from stages.source_model_extraction import work_packets, validate_response
    cache={}
    for difference in diffs:
        doc=difference['document_id']; focal=tuple(difference['focal_range'])
        source=read(difference['source_path'])
        text=next(b['text'] for b in source['source_blocks'] if b['block_id']==focal[0])
        parts.extend([f'<article><h2>{esc(doc)} · {esc(focal[0])}</h2>',
                      f'<p>本次抽取范围：字符 {focal[1]}–{focal[2]}；下方保留该段完整原文。</p>',
                      f'<pre>{esc(text)}</pre><div class="arms">'])
        for mode,label in [('local','邻近上下文'),('full_article','完整文章上下文')]:
            if (doc,mode) not in cache:
                directory=root/'runs'/doc/mode
                data=read(directory/'sources'/doc/'source_extraction.json')
                bundle=data['model_text_bundle']
                packets={scope(p):p for p in work_packets(data,bundle)}
                summary=read(directory/'summary.json')
                export=Path(summary['export_dir'])
                published={json.loads(line)['observation_id'] for line in (export/'usable_extractions.jsonl').read_text(encoding='utf8').splitlines()}
                cache[doc,mode]=(data,bundle,packets,export,published)
            data,bundle,packets,export,published=cache[doc,mode]
            packet=packets[focal]; response=difference['raw_responses'][mode]
            parts.append(f'<section><h3>{label}</h3><p><a href="{esc((export/"report.html").as_uri())}">查看本组原文结果、表格与图片链接</a></p>')
            parts.append('<table><tr><th>性质 / 材料</th><th>值 / 单位</th><th>校验与导出</th></tr>')
            for item in response.get('observations',[]):
                accepted,issues,_=validate_response(data,packet,{'observations':[item],'unresolved':[],'has_more':False},bundle['target_ids'])
                exported=bool(accepted) and all(r['observation_id'] in published for r in accepted)
                status='已导出，语义待核对' if exported else '引用校验通过，导出需核对' if accepted else '未通过引用校验'
                reasons='；'.join(reason_labels.get(i['reason'],i['reason']) for i in issues)
                if not isinstance(item,dict):
                    parts.append(f'<tr><td colspan="2">{esc(item)}</td><td class="bad">{esc(reasons)}</td></tr>'); continue
                parts.append(f'<tr><td>{esc(quote(item.get("property")))}<br><b>材料：</b>{esc(quote(item.get("material")))}</td>'
                    f'<td>{esc(quote(item.get("value")))}<br><b>单位：</b>{esc(quote(item.get("unit")))}</td>'
                    f'<td class="{"ok" if exported else "bad"}">{status}<br>{esc(reasons)}</td></tr>')
            parts.append('</table><details><summary>完整模型响应（含条件和理由）</summary><pre>'+esc(json.dumps(response,ensure_ascii=False,indent=2))+'</pre></details></section>')
        parts.append('</div></article>')
    (root/'review.html').write_text('\n'.join(parts),encoding='utf8')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','run','compare'))
    parser.add_argument('--output-root',type=Path,required=True)
    parser.add_argument('--stage0-root',type=Path)
    parser.add_argument('--documents',nargs='+')
    parser.add_argument('--config-path',type=Path,default=DEFAULT_CONFIG_PATH)
    parser.add_argument('--asset-roots',type=Path,nargs='+',default=[])
    parser.add_argument('--max-requests-per-arm',type=int,default=3)
    parser.add_argument('--workers',type=int,default=2)
    parser.add_argument('--modes',nargs='+',choices=('local','full_article'),default=['local','full_article'])
    args=parser.parse_args()
    if args.action=='prepare':
        if not args.stage0_root or not args.documents: parser.error('prepare needs --stage0-root and --documents')
        result=prepare(args.stage0_root,args.output_root,args.documents,args.config_path,args.asset_roots)
    elif args.action=='run': result=execute(args.output_root,args.max_requests_per_arm,args.workers,args.modes)
    else: result=compare(args.output_root)
    print(json.dumps({k:v for k,v in result.items() if k not in {'documents','metrics','rules'}},ensure_ascii=True))

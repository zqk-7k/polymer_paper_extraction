"""Apply semantic views to existing results without invoking a model or overwriting input."""
import argparse
import hashlib
from html import escape
import json
from collections import Counter
from pathlib import Path
from stages.source_semantic_normalization import normalize_observations, VERSION


def render_normalized_report(rows, path):
    parts=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>原始结果与语义归一</title>',
        '<style>body{font:15px/1.6 system-ui;margin:24px;color:#203044}table{border-collapse:collapse;width:100%}td,th{padding:10px;border-bottom:1px solid #ddd;text-align:left;vertical-align:top}th{background:#eef3fa}td{max-width:380px;overflow-wrap:anywhere}input{padding:10px;width:60%}pre{white-space:pre-wrap}</style>',
        f'<h1>原始结果与语义归一</h1><p>{len(rows)}条原始模型记录。规范解释单独展示，未覆盖原值，未改变发布状态；阈值和条件不作为独立测量新增。</p>',
        '<input id="q" placeholder="搜索文章、性质、值或归一规则"><table><thead><tr><th>文章 / 来源</th><th>原性质</th><th>原值 / 单位</th><th>规范解释与依据</th></tr></thead><tbody>']
    for r in rows:
        views=r.get('semantic_normalization',{})
        descriptions=[f"{v['property_name']} = {v['value']} {v.get('unit') or ''}；{v['relation']}；{v['rule']}" for v in views.get('interpretations',[])]
        descriptions+=['待解释：'+u for u in views.get('unresolved',[])]
        parts.append('<tr>'+''.join('<td>'+escape(str(v)).replace('\n','<br>')+'</td>' for v in (
            r['document_id']+'\n'+str(r.get('source_locator') or ''),r['property_name_raw'],
            str(r['value_raw'])+'\n'+str(r.get('unit_raw') or ''),'\n'.join(descriptions) or '保持原始记录'))+'</tr>')
    parts.append('</tbody></table><script>q.oninput=()=>document.querySelectorAll("tbody tr").forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(q.value.toLowerCase()))</script></html>')
    Path(path).write_text('\n'.join(parts),encoding='utf-8')


def normalize_batch(summary_path, output):
    summary_path,output=Path(summary_path),Path(output)
    if output.exists(): raise ValueError('Use a new output directory')
    source_summary=json.loads(summary_path.read_text(encoding='utf-8'))
    documents=source_summary['documents']
    rows=[]; documents_out=[]; hashes={}
    output.mkdir(parents=True)
    for doc in documents:
        # Support a single workflow run, batch runs, and a selected-run manifest.
        prior_summary=Path(doc['selected_summary']) if doc.get('selected_summary') else (
            summary_path if source_summary.get('export_dir') else summary_path.parent/'runs'/doc['document_id']/'summary.json')
        s=json.loads(prior_summary.read_text(encoding='utf-8'))
        src=Path(doc['model_results']) if doc.get('model_results') else Path(s['export_dir'])/'model_extractions.jsonl'
        originals=[r for line in src.read_text(encoding='utf-8').splitlines()
                   if (r:=json.loads(line))['document_id']==doc['document_id']]
        request=next(prior_summary.parent.glob('calls/'+doc['document_id']+'/**/request.json'),None)
        if request is None: raise ValueError(f"Missing request packet for {doc['document_id']}")
        packet=json.loads(json.loads(request.read_text(encoding='utf-8'))['user_message'])['packet']
        assert packet['document_id']==doc['document_id']
        normalized=normalize_observations(originals,packet)
        assert len(normalized)==len(originals)
        for a,b in zip(originals,normalized):
            assert {k:v for k,v in a.items() if k!='semantic_normalization'}=={k:v for k,v in b.items() if k!='semantic_normalization'}
        root=output/'runs'/doc['document_id']; export=root/'export';export.mkdir(parents=True)
        target=export/'model_extractions.jsonl'
        target.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in normalized),encoding='utf-8')
        s['documents']=[d for d in s['documents'] if d['document_id']==doc['document_id']]
        s['export_dir']=str(export.resolve())
        (root/'summary.json').write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8')
        documents_out.append({**doc,'model_results':str(target.resolve()),'selected_summary':str((root/'summary.json').resolve()),
            'model_rows':len(normalized),'model_results_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
            'input_model_results_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),
            'normalization_version':VERSION})
        rows+=normalized
        for path in (src,request): hashes[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
    rules=Counter(v['rule'] for r in rows for v in r['semantic_normalization']['interpretations'])
    result={'schema_version':VERSION,'documents':documents_out,'model_rows':len(rows),
            'rows_with_interpretations':sum(bool(r['semantic_normalization']['interpretations']) for r in rows),
            'interpretation_rule_counts':dict(rules),'api_requests':0,'input_hashes':hashes}
    (output/'all_model_extractions.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
    (output/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    render_normalized_report(rows,output/'index.html')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--summary',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    a=p.parse_args();s=normalize_batch(a.summary,a.output)
    print(json.dumps({k:v for k,v in s.items() if k not in ('documents','input_hashes')},ensure_ascii=False))

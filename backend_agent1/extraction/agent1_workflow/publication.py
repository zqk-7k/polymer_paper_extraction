"""Raw-record report; HTML escaping only, no scientific formatting/conversion."""
from html import escape
from pathlib import Path
import json

def publish(branch):
    branch=Path(branch)
    data=json.loads((branch/'final.json').read_text(encoding='utf-8-sig'))
    rows=data['observations']
    def cell(v):return escape(json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else str(v if v is not None else ''))
    headings=['样品/材料','性质','原值','原单位','状态','待核原因']
    body=''.join('<tr>'+''.join('<td>'+cell(v)+'</td>' for v in [r.get('article_sample_label_raw') or r.get('sample_id') or r.get('entity_id'),r.get('property_name_raw'),r.get('value_raw'),r.get('unit_raw'),r.get('status'),r.get('reasons')])+'</tr>' for r in rows)
    content='<!doctype html><meta charset="utf-8"><title>'+cell(data['document_id'])+'</title><style>body{font-family:system-ui;margin:32px}table{border-collapse:collapse;width:100%}td,th{padding:8px;border:1px solid #ddd;text-align:left;vertical-align:top}th{background:#eef3f8}</style>'
    content+='<h1>'+cell(data['document_id'])+'</h1><p>agent1 可选链路；原值导出，未执行模型质检、单位转换或图中数据抽取。extracted_uncategorized 为未分类抽取，不等于采用。</p><p><a href="final.json">完整 JSON</a> · <a href="review.json">待核</a> · <a href="uncategorized_properties.json">未分类/单体标注</a> · <a href="candidate_ledger.json">去向台账</a></p>'
    content+='<table><thead><tr>'+''.join('<th>'+h+'</th>' for h in headings)+'</tr></thead><tbody>'+body+'</tbody></table>'
    (branch/'report.html').write_text(content,encoding='utf-8')

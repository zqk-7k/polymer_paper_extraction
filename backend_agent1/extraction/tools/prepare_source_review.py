"""Prepare a source-only blind review packet without showing model predictions."""
import argparse
import hashlib
import json
from pathlib import Path
from html import escape

from stages.sample_catalog import source_index
from tools.source_evidence_view import evidence_view


def prepare(input_root, output_root, count=60, seed='source-review-20260928', exclude_labels=()):
    output=Path(output_root)
    if output.exists():
        raise ValueError('Output already exists')
    excluded=set()
    for path in exclude_labels:
        data=json.loads(Path(path).read_text(encoding='utf-8'))
        excluded.update((r['document_id'],r['source_cell_id']) for r in data['labels'])
    candidates=[]; tables=[]; hashes={}
    for path in sorted(Path(input_root).glob('reference_no_*/stage0_blocks.json')):
        content=path.read_bytes(); hashes[str(path.resolve())]=hashlib.sha256(content).hexdigest()
        source=json.loads(content); blocks,cells=source_index(source); doc=source['document_id']
        grouped={}
        for c in cells.values():
            grouped.setdefault(c['table_id'],[]).append(c)
            if c['row_index']>0 and c['text'] and (doc,c['cell_id']) not in excluded:
                candidates.append({'document_id':doc,'table_id':c['table_id'],'source_cell_id':c['cell_id'],'value_raw':c['text']})
        for bid,cc in grouped.items():
            tables.append({'document_id':doc,'table_id':bid,'cells':cc,'caption':blocks[bid].get('caption'),'table_notes':blocks[bid].get('table_notes',[]),'page':blocks[bid].get('page')})
    # Round-robin documents after deterministic randomization, not output-based sampling.
    ranked=sorted(candidates,key=lambda r:hashlib.sha256((seed+r['document_id']+r['source_cell_id']).encode()).hexdigest())
    buckets={}
    for r in ranked:buckets.setdefault(r['document_id'],[]).append(r)
    selected=[]
    while len(selected)<count and any(buckets.values()):
        for doc in sorted(buckets):
            if buckets[doc] and len(selected)<count:selected.append(buckets[doc].pop(0))
    packet={'schema_version':'source_blind_review_packet.v1','review_status':'awaiting_independent_review','seed':seed,
            'sampling_frame':'nonempty source cells after first row; includes non-measurements to detect false inclusion',
            'source_hashes':hashes,'targets':[{**r,'review':{'role':None,'expected_property_header_cell_ids':None,'expected_sample_axis_cell_ids':None,'expected_context_cell_ids':None,'notes':None}} for r in selected]}
    output.mkdir(parents=True)
    (output/'review_packet.json').write_text(json.dumps(packet,ensure_ascii=False,indent=2),encoding='utf-8')
    html=['<!doctype html><meta charset="utf-8"><title>独立原表复核包</title><h1>独立原表复核包</h1><p>仅展示来源，不展示程序或模型答案。请先判断该格是性质、样品、条件、表头、备注还是缺失值，再记录对应依据。空白结论不计为通过。</p><ol>']
    for i,r in enumerate(selected):
        html.append('<li>'+escape(r['document_id']+' / '+r['source_cell_id']+' / '+r['value_raw'])+f' <button data-observation="{i}">查看原表</button></li>')
    html += ['</ol>',evidence_view({'observations':selected,'tables':tables})]
    (output/'review.html').write_text('\n'.join(html),encoding='utf-8')
    return {'targets':len(selected),'documents':len({r['document_id'] for r in selected}),'review_status':packet['review_status']}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input-root',required=True);p.add_argument('--output-root',required=True)
    p.add_argument('--count',type=int,default=60);p.add_argument('--exclude-labels',nargs='*',default=[])
    print(json.dumps(prepare(**vars(p.parse_args()))))


if __name__=='__main__':main()

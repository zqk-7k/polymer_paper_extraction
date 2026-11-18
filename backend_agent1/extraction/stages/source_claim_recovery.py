"""Trace old claims to saved sources, without promoting interpretations to measurements."""
import re


def referenced_blocks(value):
    found=set()
    if isinstance(value,dict):
        for key,item in value.items():
            if key=='block_id' and isinstance(item,str):
                found.add(item)
            elif key=='source_block_ids' and isinstance(item,list):
                found.update(x for x in item if isinstance(x,str))
            elif isinstance(item,(dict,list)):
                found.update(referenced_blocks(item))
    elif isinstance(value,list):
        for item in value:
            found.update(referenced_blocks(item))
    return found


def trace_claim(claim, blocks, cells, stage6_evidence=()):
    refs=referenced_blocks(claim['original'])
    evidence_by_id={}
    for entry in stage6_evidence:
        if entry.get('evidence_id'):
            evidence_by_id.setdefault(entry['evidence_id'],[]).append(entry)
    resolved, missing, ambiguous = [], [], []
    # Primary publication members are copied from the merged payload. Historical
    # Stage4T/R and unmerged series-point IDs do not belong to that namespace.
    if claim.get('claim_kind') == 'publication':
        ids={eid for member in claim['original'].get('members',[])
             if member.get('collection') != 'property_series.points'
             for eid in member.get('original_record',{}).get('evidence_ids',[])}
        for eid in sorted(ids):
            entries=evidence_by_id.get(eid,[])
            if not entries:
                missing.append(eid)
            elif len(entries)!=1:
                ambiguous.append(eid)
            elif entries[0].get('block_id'):
                entry=entries[0]; refs.add(entry['block_id'])
                quote=entry.get('source_sentence') or ''
                source=blocks.get(entry['block_id'],{}).get('text') or ''
                resolved.append({'evidence_id':eid,'block_id':entry['block_id'],
                                 'quote_exact_in_saved_text':bool(quote and quote in source)})
    refs=sorted(refs)
    present=[bid for bid in refs if bid in blocks]
    texts=[bid for bid in present if blocks[bid].get('type')=='text']
    tables=[bid for bid in present if blocks[bid].get('type')=='table']
    original=claim['original']
    value=(original.get('identity') or original.get('effective_candidate') or original.get('record') or {}).get('value_raw')
    exact=[c['cell_id'] for c in cells.values() if c['table_id'] in tables and str(value).strip()==c['text'].strip()]
    # Matching a value alone cannot establish the property/sample relationship.
    status=('located_source_cells' if claim['observation_ids'] else 'source_context_only' if claim['disposition']=='source_context_only'
            else 'table_value_candidates' if exact else 'text_evidence_available' if texts else 'table_reference_needs_interpretation' if tables
            else 'referenced_blocks_missing' if refs else 'no_source_locator')
    return {'status':status,'referenced_block_ids':refs,'available_text_block_ids':texts,
            'resolved_stage6_evidence':resolved,'missing_stage6_evidence_ids':missing,
            'ambiguous_stage6_evidence_ids':ambiguous,
            'available_table_block_ids':tables,'missing_block_ids':[b for b in refs if b not in blocks],
            'candidate_cell_ids':exact,'auto_accepted':False,
            'basis':'source_reference_recheck; value-only candidates do not certify sample/property bindings'}

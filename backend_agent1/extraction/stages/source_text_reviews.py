"""Replay local semantic reviews only against the exact, preserved source text."""
import json
from pathlib import Path

from stages.sample_catalog import digest
from stages.binding_identity import build_article_sample_key


DEFAULT_REVIEWS = Path(__file__).resolve().parents[1] / 'config/source_text_reviews.v1.json'


def reviewed_text_observations(document_id, blocks, registry=None):
    registry = json.loads(DEFAULT_REVIEWS.read_text(encoding='utf-8')) if registry is None else registry
    if registry.get('schema_version') != 'source_text_reviews.v1':
        raise ValueError('Unsupported source text review registry')
    by_id = {b['block_id']: b for b in blocks}
    rows, issues, seen = [], [], set()
    for item in registry['reviews']:
        if item['document_id'] != document_id:
            continue
        bid = item['block_id']
        text = (by_id.get(bid) or {}).get('text') or ''
        spans = item['spans']
        support=item.get('supporting_sample')
        support_text=((by_id.get(support['block_id']) or {}).get('text') or '') if support else ''
        support_valid=bool(support and digest(support_text)==support['source_text_sha256']
                           and 0 <= support['span']['start'] < support['span']['end'] <= len(support_text)
                           and support_text[support['span']['start']:support['span']['end']]==support['span']['text'])
        valid = (digest(text) == item['source_text_sha256'] and item.get('reviewer') and item.get('basis')
                 and {'property','value','unit'} <= spans.keys() and ('sample' in spans or support_valid)
                 and (not support or support_valid)
                 and all(key in spans for key in item.get('condition_fields', {}))
                 and all(isinstance(s['start'],int) and isinstance(s['end'],int)
                         and 0 <= s['start'] < s['end'] <= len(text)
                         and text[s['start']:s['end']] == s['text'] for s in spans.values()))
        if not valid:
            issues.append({'review_id':item['review_id'],'block_id':bid,'reason':'review_source_changed_or_invalid',
                           'action':'review_only_this_assignment_again'})
            continue
        locator = f'{bid}:chars:{spans["value"]["start"]}:{spans["value"]["end"]}'
        if locator in seen:
            raise ValueError('Duplicate reviewed text assignment')
        seen.add(locator)
        start, end = min(s['start'] for s in spans.values()), max(s['end'] for s in spans.values())
        method = spans.get('method')
        label=spans['sample']['text'] if 'sample' in spans else support['span']['text']
        contexts = ([{'name_raw':'measurement method','value_raw':method['text'],'source_block_id':bid,
                      'source_span':method}] if method else [])
        contexts.extend({'name_raw': name, 'value_raw': spans[key]['text'],
                         'source_block_id': bid, 'source_span': spans[key]}
                        for key, name in item.get('condition_fields', {}).items())
        rows.append({'observation_id':'text_observation_' + digest([document_id,locator])[:24],
            'document_id':document_id,'source_kind':'text','source_block_id':bid,'source_locator':locator,
            'source_cell_id':None,'table_id':None,'source_text_sha256':digest(text),'source_spans':spans,
            'source_excerpt':text[start:end], 'source_excerpt_span':{'start':start,'end':end},
            'value_raw':spans['value']['text'],'value_normalized':None,
            'property_name_raw':spans['property']['text'],'property_header_path':[], 'property_header_cell_ids':[],
            'sample_axis_cell_ids':[],'article_sample_label_raw':label,
            'article_sample_key':build_article_sample_key(document_id,bid,label,variant_context={'method':method,'source_value_span':spans['value']}),
            'source_support':[support] if support_valid else [],
            'sample_label_basis':'reviewed_explicit_source_spans','sample_id':None,'entity_id':None,'identity_status':'article_label_only',
            'unit_raw':spans['unit']['text'],'unit_status':'source_token','condition_context_raw':contexts,
            'conditions_status':'not_exhaustively_extracted','record_kind':'property','extraction_status':'usable','review_fields':[],
            'evidence_basis':'codex_local_source_review','review_id':item['review_id'],'review_basis':item['basis'],
            'historical_request_verified':False,'standard_property_code':item['standard_property_code'],
            'standard_status':'standard_alias' if item['standard_property_code'] else 'source_name_only',
            'standard_mapping_reasons':['reviewed_property_definition'],
            'reviewed_target_ids':item.get('target_ids',[]),
            'claim_ids':[],'legacy_final_measurement_ids':[]})
    return rows, issues

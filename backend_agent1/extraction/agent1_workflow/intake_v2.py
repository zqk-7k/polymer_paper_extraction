"""Permissive transport shapes with explicit conflicts and untouched scientific values."""
from copy import deepcopy
from evidence_text import original_span

def as_list(value):
    if value is None:return []
    return value if isinstance(value,list) else [value]

def observation(value,blocks=None):
    if not isinstance(value,dict):return {'value_raw':None,'unparsed_original':deepcopy(value)}
    o=deepcopy(value);changes=[]
    for field in ['conditions','evidence_refs','sample_ids','qualifiers_raw']:
        if field not in o:continue
        if field=='conditions' and isinstance(o[field],dict) and 'name_raw' not in o[field]:
            o[field]=[{'name_raw':k,'value_raw':v,'transport_shape_origin':'condition_map'} for k,v in o[field].items()]
            changes.append('condition_map_to_list')
        elif not isinstance(o[field],list):o[field]=as_list(o[field]);changes.append(field+'_to_list')
    def visit(node):
        if isinstance(node,list):return [visit(v) for v in node]
        if not isinstance(node,dict):return node
        r={k:visit(v) for k,v in node.items()}
        if 'evidence_refs' in r:r['evidence_refs']=as_list(r['evidence_refs'])
        if r.get('source_block_id') and r.get('quote') and blocks:
            block=blocks.get(r['source_block_id'],{})
            if block.get('type') in ('text','paragraph','title'):
                span=original_span(block.get('text',''),r['quote'])
                if span and span['quote']!=r['quote']:
                    r['quote_model_raw']=r['quote'];r['quote']=span['quote']
                    r['evidence_span_v2']={k:v for k,v in span.items() if k!='quote'}
                    changes.append('unique_original_evidence_span')
        return r
    o=visit(o)
    o['intake_adaptations']=changes
    assert o.get('value_raw')==value.get('value_raw') and o.get('unit_raw')==value.get('unit_raw')
    return o

def response(data):
    """New shared spectrum groups and old flat observations coexist."""
    d=deepcopy(data);observations=as_list(d.get('observations'))
    for group_index,g in enumerate(as_list(d.get('spectrum_groups'))):
        if not isinstance(g,dict):
            observations.append({'value_raw':None,'unparsed_spectrum_group':g});continue
        common=g.get('common') or {k:v for k,v in g.items() if k not in ('peaks','group_id')}
        for peak_index,peak in enumerate(as_list(g.get('peaks'))):
            if not isinstance(peak,dict):observations.append({'value_raw':None,'unparsed_spectrum_peak':peak});continue
            o={**deepcopy(common),**deepcopy(peak)}
            o['conditions']=deepcopy(common.get('conditions',[]))+deepcopy(peak.get('conditions',[]))
            o['spectrum_group_ref']=g.get('group_id',str(group_index))
            o['spectrum_peak_index']=peak_index
            observations.append(o)
    d['observations']=observations
    for field in ['methods','unresolved']:
        if field in d:d[field]=as_list(d[field])
    return d

def table_response(data):
    d=deepcopy(data)
    for field in ['property_axes','subject_axes','condition_axes','cell_overrides','notes','unresolved','symbol_rules','field_decisions']:
        if field in d:d[field]=as_list(d[field])
    for field in ['property_axes','subject_axes','condition_axes','symbol_rules','field_decisions']:
        for a in d.get(field,[]):
            if not isinstance(a,dict):continue
            for name in ['indices','source_cell_ids','conditions','evidence_refs']:
                if name in a:a[name]=as_list(a[name])
            scope=a.get('applies_to')
            if isinstance(scope,dict) and 'indices' in scope:scope['indices']=as_list(scope['indices'])
            for c in a.get('conditions',[]):
                if isinstance(c,dict) and 'evidence_refs' in c:c['evidence_refs']=as_list(c['evidence_refs'])
            if field=='symbol_rules':
                regime=a.get('regime')
                if isinstance(regime,str):a['regime']=regime.strip().replace(' ','_').replace('-','_')
                for r in a.get('evidence_refs',[]):
                    if not isinstance(r,dict):continue
                    if not r.get('source_id'):r['source_id']=r.get('source_cell_id') or r.get('source_block_id')
    return d

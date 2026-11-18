"""Normalize transport containers before request-shape validation; preserve raw audits."""
from copy import deepcopy
from dataclasses import replace
from intake_v2 import as_list,table_response

def canonical(data,stage):
    if not isinstance(data,dict):return data
    if stage=='stage4t_table_interpretation':
        d=table_response(data)
        for field in ['property_axes','subject_axes','condition_axes','cell_overrides']:
            if any(not isinstance(x,dict) for x in d.get(field,[])):
                raise ValueError('Unparseable table relation retained in raw audit: '+field)
        for field in ['symbol_rules','field_decisions']:
            if field in d:
                d[field]=[x if isinstance(x,dict) else {'unparsed_original':deepcopy(x),
                    'receipt_issue':'unparseable_optional_annotation_no_override_authority'} for x in d[field]]
        if isinstance(d.get('property_axes'),list):
            d.setdefault('symbol_rules',[]);d.setdefault('field_decisions',[])
        return d
    if stage not in ('stage4_property','stage5_characterization'):return data
    d=deepcopy(data)
    for field in ['observations','methods','unresolved']:
        if field in d:d[field]=as_list(d[field])
    if 'observations' in d:
        d['observations']=[x if isinstance(x,dict) else {'value_raw':None,'unparsed_original':deepcopy(x),
            'receipt_issue':'unparseable_observation_retained_without_scientific_inference'} for x in d['observations']]
    if stage=='stage5_characterization' and isinstance(d.get('spectrum_groups'),list) and 'observations' not in d:
        d['observations']=[]
    return d

def install():
    import execution
    original=execution.LLMClient.from_pipeline_config
    def configured(*args,**kwargs):
        client=original(*args,**kwargs);stage=kwargs.get('stage');raw_call=client.call_json
        def call(system,user_message,**options):
            result=raw_call(system,user_message,**options)
            return replace(result,data=canonical(result.data,stage))
        client.call_json=call
        return client
    execution.LLMClient.from_pipeline_config=staticmethod(configured)

def verify_live_receipts(root):
    """Successful strict responses also pass the wider final receiving gateway."""
    from common import read,digest
    rows=[]
    def scientific_fields(value):
        result=[]
        def visit(node):
            if isinstance(node,list):
                for x in node:visit(x)
            elif isinstance(node,dict):
                for k,v in node.items():
                    if k in ('value_raw','unit_raw','sample_id','target_id','symbol_raw') and v is not None:result.append((k,digest(v)))
                    visit(v)
        visit(value)
        return sorted(result)
    for path in root.glob('runs/*/*/tasks/*.json'):
        saved=read(path);data=saved.get('data',{});stage=saved.get('stage')
        normalized=canonical(data,stage)
        arrays=['property_axes','subject_axes','condition_axes','cell_overrides','notes','unresolved','symbol_rules','field_decisions'] if stage=='stage4t_table_interpretation' else ['observations','unresolved']+(['methods'] if stage=='stage5_characterization' else []) if stage in ('stage4_property','stage5_characterization') else []
        valid=all(isinstance(normalized.get(k),list) for k in arrays)
        rows.append({'task':str(path.relative_to(root)),'stage':stage,'valid':valid,
            'successful_response_unchanged':digest(data)==digest(normalized),
            'scientific_raw_fields_unchanged':scientific_fields(data)==scientific_fields(normalized),
            'raw_request_audit_preserved':True})
    return rows

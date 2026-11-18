"""Version-bound evidence handles and explicit role provenance; no semantic inference."""
from copy import deepcopy
from common import digest

GUIDANCE='''
Evidence handoff contract: shared_evidence_refs contains exact source references,
keyed by content-version-bound IDs. You may return {"evidence_ref_id":"ID"}
where an evidence_refs member is expected. Prefer these handles to retyping a long
paragraph; never invent a handle. A handle is scoped to this task and input version.
Keep values and units in the original source form. Do not compute any quantities.
Data roles: measured means the source reports an experimental result for that quantity;
calculated means the source explicitly obtains it by an equation/computation from
other quantities. Do not classify a whole table from one footnote. For an experimental
fit parameter or unclear derivation, use unknown and role_detail experimental_fit
or unresolved, retaining role_evidence_refs and role_reason_raw. An experimental
fit parameter is a separate review channel and is not scored in this project.
For every property_axis, return role_evidence_refs (source references or handles)
and role_reason_raw explaining only the source basis. unknown is allowed; do not
guess measured from a numeric-looking cell. Definitions apply to every table.
'''

def prepare(task,raw,notes):
    result=deepcopy(task);augmented=deepcopy(raw);packet=result['packet'];tid=task['table_id']
    sources=packet.setdefault('evidence_sources',[]);known={s['source_id'] for s in sources}
    for note in notes:
        assert note['table_id']==tid and note['source_pdf_sha256'] and note['verified_table_binding']
        sid=note['source_id']
        if sid not in known:
            sources.append({'source_id':sid,'text':note['text'],'kind':'pdf_table_footnote','table_id':tid,
                            'source_pdf_sha256':note['source_pdf_sha256'],'page_1based':note['page_1based'],'marker':note['marker']})
        augmented['elements'].append({'block_id':sid,'type':'text','text':note['text'],'page':note['page_1based'],
            'source_block_index':len(augmented['elements']),'section':'verified_table_notes','table_id':tid,
            'source_provenance':deepcopy(note)})
    refs=deepcopy(packet.get('shared_evidence_refs',{}))
    for source in sources:
        if not source.get('text'):continue
        sid=source['source_id'];key='ev_'+digest([tid,sid,source['text']])[:24]
        refs[key]={'kind':'text','source_block_id':sid,'quote':source['text']}
    packet['shared_evidence_refs']=refs
    packet['evidence_bundle_version']=digest(sources)
    packet['evidence_handoff_version']='source_handles_and_roles.v1'
    return result,augmented

def expand(data,packet):
    refs=packet.get('shared_evidence_refs',{})
    def visit(value):
        if isinstance(value,list):return [visit(v) for v in value]
        if isinstance(value,dict):
            if 'evidence_ref_id' in value:
                key=value['evidence_ref_id']
                if key not in refs:return {**deepcopy(value),'reference_resolution_error':'unknown_version_bound_handle'}
                if any(k!='evidence_ref_id' and refs[key].get(k)!=v for k,v in value.items()):
                    return {**deepcopy(value),'reference_resolution_error':'conflicting_handle_fields'}
                return deepcopy(refs[key])
            return {k:visit(v) for k,v in value.items()}
        return value
    return visit(data)

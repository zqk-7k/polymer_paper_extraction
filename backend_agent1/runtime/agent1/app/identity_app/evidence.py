"""Version-bound projections of actual tool receipts; no query on page read."""
from copy import deepcopy
from .storage import read, file_hash

OPERATIONS = {'prepare_component', 'resolve', 'public_lookup', 'profile', 'name_graph', 'declared_cru', 'verify_name', 'check_structure', 'check_substituent', 'review','bind_receipt','prepare_constitution','derive_constitution','assemble','review_naming'}

def strip_images(value):
    if isinstance(value, list):return [strip_images(x) for x in value]
    if isinstance(value, dict):return {k:strip_images(v) for k,v in value.items() if k not in ('image','depiction')}
    return value

def receipts_for(job, inherited=None):
    records = deepcopy(inherited or {})
    for path in sorted((job/'tool-events').glob('*.json')):
        r = read(path,{})
        if r.get('operation') in OPERATIONS:
            records[r['id']] = {**strip_images(r), 'sha256':file_hash(path),
                                'receipt_path':str(path), 'stored_from_actual_operation':True}
    return records

def library_summary(m, candidate):
    graphs = [candidate['graphs'][g] for g in m.get('graph_ids',[]) if g in candidate.get('graphs',{})]
    return {'name':(m.get('most_likely_name') or {}).get('text'),
            'name_basis':(m.get('most_likely_name') or {}).get('basis'),
            'formulas':[g.get('formula') for g in graphs],
            'graph_scopes':[g.get('scope') for g in graphs],
            'name_check':(m.get('naming_verification') or {}).get('status','NOT_RUN'),
            'iupac_scope_status':(m.get('iupac_assessment') or {}).get('status'),
            'tool_statuses':[{'operation':x.get('operation'),'status':x.get('status')} for x in m.get('tool_evidence',[])]}

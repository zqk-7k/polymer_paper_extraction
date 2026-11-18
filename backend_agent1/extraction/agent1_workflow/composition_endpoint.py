"""Table-local binary endpoints backed by caption order and existing identities.

No fuzzy IDs, global ratio aliases, property-value matching or state inference.
Conservative abstention is intentional for intermediate ratios and states.
"""
from copy import deepcopy
from decimal import Decimal
import re
import unicodedata

def text(value):
    return unicodedata.normalize('NFKC',str(value or '')).translate(str.maketrans({'−':'-','–':'-','‑':'-'})).strip()

def endpoint(value):
    m=re.fullmatch(r'(\d+(?:\.\d+)?)\s*[/：:]\s*(\d+(?:\.\d+)?)',text(value))
    if not m:return None
    a,b=map(Decimal,m.groups())
    if a+b not in (Decimal(1),Decimal(100)):return None
    return 0 if a>0 and b==0 else 1 if a==0 and b>0 else None

def project(table,response,identity):
    out=deepcopy(response);audit=[];caption=text(table.get('caption'))
    samples={s['sample_id']:s for s in identity.get('samples',[])}
    locator=re.search(r'\bTable\s+([\d]+|[IVXLCDM]+)\b',caption,re.I)
    names={}
    def add(label,sid):
        label=text(label)
        suffix=re.fullmatch(r'(.+?)\s*\(Table\s+([\d]+|[IVXLCDM]+)\s+endpoint\)',label,re.I)
        if suffix and locator and suffix[2].upper()==locator[1].upper():label=suffix[1].strip()
        if label:names.setdefault(label,set()).add(sid)
    for sid,s in samples.items():
        for key in ('sample_label_raw','polymer_name'):add(s.get(key),sid)
    for label,ids in identity.get('alias_index',{}).items():
        for sid in ids:
            if sid in samples:add(label,sid)
    # Token boundaries exclude a substring of another chemical code or A/B/C.
    pairs=[]
    for m in re.finditer(r'(?<![\w./-])([\w.-]+)\s*/\s*([\w.-]+)(?![\w./-])',caption):
        a,b=m.groups()
        if a!=b and len(names.get(a,set()))==len(names.get(b,set()))==1:
            ids=[next(iter(names[x])) for x in (a,b)]
            if ids[0]!=ids[1]:pairs.append((a,b,ids))
    if len(pairs)!=1:return out,audit
    first,second,ids=pairs[0];cells={c['cell_id']:c for c in table['cells']}
    for axis in out.get('subject_axes',[]):
        if axis.get('owner_scope') not in (None,'unknown','sample'):continue
        direction=axis.get('axis');indices=axis.get('indices',[])
        if direction not in ('row','column') or len(indices)!=1 or not isinstance(indices[0],int) or isinstance(indices[0],bool):continue
        coord='row_index' if direction=='row' else 'column_index'
        ortho='column_index' if direction=='row' else 'row_index'
        orthospan='column_span' if direction=='row' else 'row_span'
        refs=axis.get('source_cell_ids') or []
        if len(refs)!=1 or refs[0] not in cells:continue
        ratio=cells[refs[0]];which=endpoint(ratio.get('text'))
        if which is None or ratio[coord]!=indices[0]:continue
        headers=[c for c in cells.values() if re.search(r'\bcomposition\b|组成|组分比',text(c.get('text')),re.I)
                 and c[coord]<ratio[coord] and c[ortho]<=ratio[ortho]<c[ortho]+c.get(orthospan,1)]
        if len(headers)!=1:continue
        sid=ids[which];sample=samples[sid]
        # An endpoint identifies a component, not a processing/test state.
        if sample.get('sample_kind')!='unspecified' or sample.get('state_description'):continue
        claim=axis.get('sample_id')
        proof={'table_id':table['table_id'],'caption_raw':table.get('caption'),
               'component_order':[first,second],'composition_header_ref':headers[0]['cell_id'],
               'ratio_cell_ref':ratio['cell_id'],'ratio_raw':ratio.get('text'),
               'selected_component':[first,second][which],'sample_id':sid,
               'directory_label_raw':sample.get('sample_label_raw'),
               'original_sample_id':claim,'axis':direction,'index':indices[0],
               'state_scope':'not_inferred','basis':'table_local_binary_endpoint'}
        if claim in samples:
            if claim!=sid:audit.append({**proof,'outcome':'existing_identity_conflict_preserved'})
            continue
        if axis.get('entity_id') and axis['entity_id']!=sample.get('refers_to_entity'):
            audit.append({**proof,'outcome':'existing_entity_conflict_preserved'});continue
        from subject_scope import permits
        data=[c for c in cells.values() if c[coord]==indices[0] and c[ortho]>ratio[ortho] and permits(axis.get('region'),c)]
        if not data:continue
        # Keep a pre-existing lane restriction; never widen a subject's scope.
        axis['region']={'rows':sorted({c['row_index'] for c in data}),'columns':sorted({c['column_index'] for c in data})}
        axis.update(sample_id=sid,owner_scope='sample',composition_endpoint_binding=proof)
        audit.append({**proof,'outcome':'bound'})
    return out,audit

def annotate(observations,table,response):
    from subject_scope import permits
    cells={c['cell_id']:c for c in table['cells']}
    for o in observations:
        cell=cells.get(o.get('source_cell_id'))
        if not cell:continue
        candidates=[]
        for a in response.get('subject_axes',[]):
            p=a.get('composition_endpoint_binding')
            if not p or not permits(a.get('region'),cell):continue
            coord='row_index' if p['axis']=='row' else 'column_index'
            ortho='column_index' if p['axis']=='row' else 'row_index'
            ratio=cells[p['ratio_cell_ref']]
            if cell[coord]==p['index'] and cell[ortho]>ratio[ortho] and o.get('sample_id')==p['sample_id']:
                candidates.append(p)
        if len(candidates)==1:o['composition_endpoint_binding']=deepcopy(candidates[0])
    return observations

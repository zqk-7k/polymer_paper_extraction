"""Deterministic subject-axis projection from explicit source geometry and known IDs.

This module is assessed separately from the frozen live model entry. It never
rewrites response files or measurement cells. A header cell labelled 'Polymer
Code' is an axis title, not a chemical subject; cited per-index labels may resolve
an entity while its physical-state sample remains unspecified.
"""
from copy import deepcopy
from catalog import norm
from evidence_text import view
from ownership import graph
from common import digest,sha
LOADED_SOURCE_SHA256=sha(__file__)

def scoped_members(identity,eid,label):
    """An entity may be a family: only exact article-label matches and declared children."""
    samples={s['sample_id']:s for s in identity['samples']}
    wanted=norm(view(label)[0]);contexts={c['sample_id']:c for c in identity.get('identity_contexts',[])}
    chosen={sid for sid,s in samples.items() if s.get('refers_to_entity')==eid and any(
        norm(view(name)[0])==wanted for name in [s.get('sample_label_raw'),contexts.get(sid,{}).get('agent_label')] if name)}
    for _ in samples:
        children={sid for sid,s in samples.items() if s.get('refers_to_entity')==eid and s.get('parent_sample_id') in chosen}
        if children<=chosen:break
        chosen|=children
    return sorted(chosen)

def scope_record(row,observation,identity):
    result=deepcopy(row)
    label=observation.get('owner_label_raw') or result.get('article_sample_label_raw')
    if result.get('owner_scope')!='material' or not result.get('entity_id') or not label:return result
    eid=result['entity_id'];scope_key='material_scope_'+digest([identity['document_id'],eid,norm(view(label)[0])])[:20]
    result['material_scope']={'scope_id':scope_key,'source_label_raw':label,'parent_entity_id':eid,
        'chemical_entity_invented':False,'physical_state_assigned':False}
    result.setdefault('owner_resolution',{})['associated_sample_ids']=scoped_members(identity,eid,label)
    result['owner_resolution']['material_scope_id']=scope_key
    # The existing exact dedup key already includes series_applicability. Extend
    # that scope metadata so equal values for different family members stay distinct.
    result.setdefault('series_applicability',{})['material_scope_id']=scope_key
    return result

def canonical(table,response,identity):
    out=deepcopy(response);cells={c['cell_id']:c for c in table['cells']}
    g=identity.get('ownership_graph') or graph(identity)
    aliases={}
    for label,ids in g['material_alias_index'].items():aliases.setdefault(norm(view(label)[0]),set()).update(ids)
    entities={e['entity_id']:e for e in g['entities']};audit=[];axes=[]
    for number,axis in enumerate(out.get('subject_axes',[])):
        direction=axis.get('axis');indices=axis.get('indices');refs=axis.get('source_cell_ids') or []
        known_label=norm(view(axis.get('owner_label_raw') or '')[0]) in aliases
        material_claim=axis.get('owner_scope')=='material'
        declared_eid=axis.get('entity_id')
        if not declared_eid and material_claim and axis.get('sample_id'):
            declared_eid=next((s.get('refers_to_entity') for s in identity['samples'] if s['sample_id']==axis['sample_id']),None)
        if ((axis.get('sample_id') or axis.get('entity_id') or known_label) and not material_claim or
            axis.get('owner_scope') in ('component','reference','group') or
            direction not in ('row','column') or not isinstance(indices,list) or not indices or not refs or any(cid not in cells for cid in refs)):
            axes.append(axis);continue
        if any(not isinstance(i,int) or isinstance(i,bool) for i in indices):axes.append(axis);continue
        indices=list(dict.fromkeys(indices))
        coordinate='row_index' if direction=='row' else 'column_index'
        span='row_span' if direction=='row' else 'column_span'
        orthogonal='column_index' if direction=='row' else 'row_index'
        replacements=[];resolved=[];unresolved=[]
        for index in indices:
            candidates=[]
            for cid in refs:
                cell=cells[cid]
                if not (cell[coordinate]<=index<cell[coordinate]+cell.get(span,1)):continue
                eids=aliases.get(norm(view(cell.get('text',''))[0]),set())
                exact_declared_label=norm(view(cell.get('text',''))[0])==norm(view(axis.get('owner_label_raw') or '')[0])
                explicit=bool(material_claim and declared_eid in entities and norm(view(cell.get('text',''))[0]) and exact_declared_label and (not eids or declared_eid in eids))
                if explicit:eid=declared_eid
                elif len(eids)==1:eid=next(iter(eids))
                else:continue
                if axis.get('entity_id') and axis['entity_id']!=eid:continue
                if known_label and eid not in aliases[norm(view(axis['owner_label_raw'])[0])]:continue
                if axis.get('sample_id'):
                    explicit=next((s for s in identity['samples'] if s['sample_id']==axis['sample_id']),{})
                    if explicit.get('refers_to_entity')!=eid:continue
                # The cited label must precede actual result cells on this index.
                later=[v for v in cells.values() if v[coordinate]==index and v[orthogonal]>cell[orthogonal]
                       and any(isinstance(p,dict) and p.get('axis') in ('row','column') and
                           v['row_index' if p['axis']=='row' else 'column_index'] in p.get('indices',[])
                           for p in out.get('property_axes',[]))]
                if not later:continue
                candidates.append((cid,eid,explicit))
            # Two matching labels are an ambiguity even if their spelling agrees.
            if len(candidates)!=1:
                replacements.append({**deepcopy(axis),'indices':[index]});unresolved.append(index);continue
            cid,eid,explicit=candidates[0]
            replacement={**deepcopy(axis),'indices':[index],'owner_scope':'material','sample_id':axis.get('sample_id'),
                'owner_label_raw':cells[cid]['text'],'entity_id':eid,'source_cell_ids':[cid],
                'owner_binding':{'entity_id':eid,'source_cell_id':cid,'table_id':table['table_id'],
                    'label_raw':cells[cid]['text'],'associated_sample_ids':scoped_members(identity,eid,cells[cid]['text']),
                    'axis':direction,'index':index,'basis':'declared_subject_axis_unique_original_label_and_existing_entity',
                    'model_explicit_entity_id':declared_eid if explicit else None,
                    'model_explicit_label_raw':axis.get('owner_label_raw') if explicit else None,
                    'state_scope':'not_assigned','member_measurements_generated':False}}
            replacements.append(replacement)
            resolved.append(index)
        if not resolved:axes.append(axis);continue
        axes.extend(replacements)
        audit.append({'axis_index':number,'original_axis':deepcopy(axis),'expanded_indices':resolved,'unresolved_indices':unresolved,
            'bindings':[r['owner_binding'] for r in replacements if r.get('owner_binding')],'scientific_values_changed':False})
    out['subject_axes']=axes
    return out,audit

def bind_records(observations,table,response):
    """Carry only canonical, source-backed owner metadata through the legacy reader."""
    cells={c['cell_id']:c for c in table['cells']}
    result=deepcopy(observations)
    for o in result:
        cell=cells.get(o.get('source_cell_id'))
        if not cell:continue
        from subject_scope import permits
        bound=[a for a in response.get('subject_axes',[]) if a.get('owner_binding') and permits(a.get('region'),cell) and
               cell['row_index' if a.get('axis')=='row' else 'column_index'] in a.get('indices',[])]
        if len(bound)!=1:continue
        axis=bound[0]
        if o.get('owner_scope')!='material' or o.get('owner_label_raw')!=axis['owner_label_raw']:continue
        o['table_material_binding']=deepcopy(axis['owner_binding']);o['entity_id']=axis['entity_id']
    return result

def receive(row,observation,identity,blocks,cells):
    """Promote only an already literal-supported fact with an explicit material axis."""
    result=deepcopy(row);binding=observation.get('table_material_binding') or {}
    cid=observation.get('source_cell_id');label_id=binding.get('source_cell_id');eid=binding.get('entity_id')
    data=cells.get(cid,{});label=cells.get(label_id,{})
    entities={e['entity_id']:e for e in identity.get('entities',[])}
    g=identity.get('ownership_graph') or graph(identity)
    ids=set()
    for name,eids in g['material_alias_index'].items():
        if norm(view(name)[0])==norm(view(label.get('text',''))[0]):ids.update(eids)
    members=scoped_members(identity,eid,label.get('text',''))
    axis=binding.get('axis');coord='row_index' if axis=='row' else 'column_index'
    orthogonal='column_index' if axis=='row' else 'row_index'
    span='row_span' if axis=='row' else 'column_span'
    geometry=bool(axis in ('row','column') and data.get(coord)==binding.get('index') and
        label.get(coord,10**9)<=data.get(coord,-1)<label.get(coord,-1)+label.get(span,1) and
        label.get(orthogonal,10**9)<data.get(orthogonal,-1))
    explicit=bool(binding.get('model_explicit_entity_id')==eid and norm(view(label.get('text',''))[0]) and
        norm(view(binding.get('model_explicit_label_raw') or '')[0])==norm(view(label.get('text',''))[0]) and (not ids or eid in ids))
    valid=bool(binding and eid in entities and cid and label_id and cid!=label_id and
        data.get('table_id')==label.get('table_id')==binding.get('table_id') and
        label.get('text')==binding.get('label_raw') and observation.get('owner_scope')=='material' and
        cid in result.get('verified_literal_source_refs',[]) and (ids=={eid} or explicit) and geometry and
        set(binding.get('associated_sample_ids',[]))==set(members))
    if not valid:return result
    result.update(owner_scope='material',sample_id=None,entity_id=eid,binding_basis=binding['basis'])
    result['owner_resolution']={'requested_scope':'material','scope':'material','sample_id':None,'entity_id':eid,
        'associated_sample_ids':binding['associated_sample_ids'],'evidence_verified':True,'reason':binding['basis'],
        'state_scope':'not_assigned','member_measurements_generated':False,'source_binding':deepcopy(binding)}
    result['reasons']=[r for r in result['reasons'] if r not in
        ('group_scope_preserved','ambiguous_alias','owner_not_resolved','material_identity_ambiguous','material_scope_evidence_missing')]
    if result['status']=='needs_review' and not result['reasons']:result['status']='adopted'
    result['core_status']=result['status']
    return result

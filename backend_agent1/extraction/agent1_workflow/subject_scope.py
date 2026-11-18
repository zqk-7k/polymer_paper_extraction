"""Source-bounded table regions; identity mappings never imply whole-row ownership."""
from copy import deepcopy
from evidence_text import view

GUIDANCE='''
Subject regions: a subject_axes entry may include region:{rows:[zero-based rows],columns:[zero-based columns]}.
Both lists delimit its DATA cells, excluding other material groups on the same row/column.
For side-by-side material/value column groups return one subject entry per material and restrict BOTH coordinates.
Never assign a left-hand material to right-hand data just because row indices agree.
For a whole-table subject without a sample-code axis use axis:"table", indices:[], region with all applicable data rows/columns,
owner_label_raw, an existing sample_id, and scope_evidence_refs:[{source_id,quote}] citing the caption or supplied prose that explicitly names the subject.
Use the table_id to cite its caption. If a concrete state is not specified, preserve material scope instead of inventing a sample state.
If scope cannot be established, leave the owner unknown and explain it in unresolved.
'''

def permits(region,cell):
    if region is None:return True
    return isinstance(region,dict) and cell['row_index'] in region.get('rows',[]) and cell['column_index'] in region.get('columns',[])

def project(task,response,identity):
    out=deepcopy(response);table=task['source_table'];cells=table['cells'];byid={c['cell_id']:c for c in cells}
    rowset={i for c in cells for i in range(c['row_index'],c['row_index']+c.get('row_span',1))}
    colset={i for c in cells for i in range(c['column_index'],c['column_index']+c.get('column_span',1))}
    audits=[];sources={s['source_id']:s.get('text','') for s in task.get('packet',{}).get('evidence_sources',[])}
    sources[table['table_id']]=str(table.get('caption') or '')
    samples={s['sample_id']:s for s in identity.get('samples',[])}
    axes=out.get('subject_axes',[])
    for pos,a in enumerate(axes):
        region=a.get('region');why=None
        if region is not None:
            valid=isinstance(region,dict) and all(isinstance(region.get(k),list) and region[k] and
                all(isinstance(i,int) and not isinstance(i,bool) for i in region[k]) and set(region[k])<=allowed
                for k,allowed in (('rows',rowset),('columns',colset)))
            if not valid:why='invalid_subject_region'
        if a.get('axis')=='table':
            refs=a.get('scope_evidence_refs') or [];label=view(a.get('owner_label_raw'))[0].casefold()
            sid=a.get('sample_id');known={}
            for k,v in identity.get('alias_index',{}).items():known.setdefault(view(k)[0].casefold(),set()).update(v)
            verified=isinstance(refs,list) and bool(refs) and bool(label) and sid in samples and known.get(label)=={sid}
            if not isinstance(refs,list):refs=[]
            for ref in refs:
                if not isinstance(ref,dict):verified=False;continue
                quote=str(ref.get('quote') or '');text=sources.get(ref.get('source_id'),'')
                verified=verified and bool(quote) and quote in text and label in view(quote)[0].casefold()
            if not verified or region is None:why='whole_table_subject_requires_unique_named_scope_evidence'
            a['axis']='row';a['indices']=sorted(rowset)
        if why:
            a.update(sample_id=None,entity_id=None,owner_label_raw=None,owner_scope='unknown')
            a.pop('region',None)
            audits.append({'axis_index':pos,'status':'owner_held_unknown','reason':why})
            continue
        if region is not None:
            audits.append({'axis_index':pos,'status':'explicit_region_preserved','region':region});continue
        # Narrow only when an explicit leaf-label cell identifies each repeated lane.
        direction=a.get('axis');coordinate='row_index' if direction=='row' else 'column_index'
        ortho='column_index' if direction=='row' else 'row_index'
        if direction not in ('row','column'):continue
        label=view(a.get('owner_label_raw'))[0].casefold()
        anchors=[byid[x] for x in a.get('source_cell_ids',[]) if x in byid and label and view(byid[x].get('text'))[0].casefold()==label]
        peers=[]
        for b in axes:
            # Overlapping parent/child headers are not parallel data lanes.
            if b.get('axis')!=direction or set(b.get('indices',[]))!=set(a.get('indices',[])):continue
            blabel=view(b.get('owner_label_raw'))[0].casefold()
            peers.extend(byid[x] for x in b.get('source_cell_ids',[]) if x in byid and blabel and view(byid[x].get('text'))[0].casefold()==blabel)
        positions=sorted({c[ortho] for c in peers})
        starts={c[ortho] for c in anchors}
        same_level=len({c[coordinate] for c in peers})==1
        if len(positions)>1 and len(starts)==1 and same_level:
            start=next(iter(starts));end=next((x for x in positions if x>start),max(colset if direction=='row' else rowset)+1)
            region={'rows':a.get('indices',[]) if direction=='row' else list(range(start,end)),
                    'columns':list(range(start,end)) if direction=='row' else a.get('indices',[])}
            a['region']=region
            audits.append({'axis_index':pos,'status':'parallel_lane_region_from_cited_labels','region':region,
                           'source_cell_ids':[c['cell_id'] for c in anchors]})
    return out,audits

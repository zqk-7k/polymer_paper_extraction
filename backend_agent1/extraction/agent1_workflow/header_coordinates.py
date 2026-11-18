"""Canonicalize explicit header geometry, without inferring condition semantics."""
from copy import deepcopy
from table_reader import matches


def canonical(table,response):
    result=deepcopy(response);audit=[]
    cells={c['cell_id']:c for c in table['cells']}
    for number,axis in enumerate(result.get('condition_axes',[])):
        if not isinstance(axis,dict):continue
        scope=axis.get('applies_to') or {}
        if not isinstance(scope,dict):continue
        old=axis.get('axis');new=scope.get('axis')
        if axis.get('value_location')!='header' or old not in ('row','column') or new not in ('row','column') or old==new:
            continue
        original=axis.get('indices') or [];indices=scope.get('indices') or []
        refs=axis.get('source_cell_ids') or []
        if not all(isinstance(v,list) for v in [original,indices,refs]) or any(not isinstance(cid,str) for cid in refs):continue
        if not original or not indices or not refs or any(cid not in cells for cid in refs):continue
        if any(not isinstance(i,int) or isinstance(i,bool) or i<0 for i in original+indices):continue
        sources=[cells[cid] for cid in refs]
        coordinate=lambda direction:('row_index','row_span') if direction=='row' else ('column_index','column_span')
        old_key,old_span=coordinate(old);new_key,new_span=coordinate(new)
        covered=lambda key,span:{i for c in sources for i in range(c[key],c[key]+c.get(span,1))}
        if covered(old_key,old_span)!=set(original) or covered(new_key,new_span)!=set(indices):continue
        # Declared subject/result axes must identify data beyond these headers.
        if any(any(matches(s,h) for s in result.get('subject_axes',[])) for h in sources):continue
        valid=True
        for index in set(indices):
            headers={h['cell_id']:h for h in sources if h[new_key]<=index<h[new_key]+h.get(new_span,1)}
            if len(headers)!=1:valid=False;break
            header=next(iter(headers.values()))
            measurements=[c for c in cells.values() if c[new_key]==index
                and any(matches(s,c) for s in result.get('subject_axes',[]))
                and any(matches(p,c) for p in result.get('property_axes',[]))]
            if not measurements or any(c[old_key]<header[old_key]+header.get(old_span,1) for c in measurements):
                valid=False;break
        if not valid:continue
        axis['axis']=new;axis['indices']=list(dict.fromkeys(indices))
        audit.append({'condition_axis_index':number,'original_axis':old,'original_indices':original,
            'effective_axis':new,'effective_indices':axis['indices'],'source_cell_ids':refs,
            'basis':'explicit_application_scope_equals_unique_preceding_raw_header_geometry'})
    return result,audit


def install():
    import mapping_contract
    base=mapping_contract.original_interpret
    if getattr(base,'_explicit_header_coordinates',False):return
    def read(table,response,target_ids,sample_ids):
        normalized,changes=canonical(table,response)
        rows,audit=base(table,normalized,target_ids,sample_ids)
        audit['header_coordinate_canonicalization']=changes
        return rows,audit
    read._explicit_header_coordinates=True
    mapping_contract.original_interpret=read

"""Align a contradictory header-axis label only when raw geometry and explicit scope agree."""
from copy import deepcopy
import sys
from common import OUT,read,write as save,sha

from table_reader import matches,condition_family

def align(task,response):
    result=deepcopy(response);table=task['source_table'];cells={c['cell_id']:c for c in table['cells']};audit=[]
    for number,axis in enumerate(result['condition_axes']):
        if condition_family(axis.get('name_raw'))!='solvent' or axis.get('value_location')!='header':continue
        scope=axis.get('applies_to',{});wanted=scope.get('axis');indices=set(axis.get('indices',[]))
        refs=axis.get('source_cell_ids',[])
        if wanted not in ('row','column') or axis.get('axis')==wanted or not indices or set(scope.get('indices',[]))!=indices:continue
        if not refs or any(cid not in cells for cid in refs):continue
        headers=[cells[c] for c in refs]
        if any(any(matches(s,c) for s in result['subject_axes']) for c in headers):continue
        varying='column_index' if wanted=='column' else 'row_index'
        fixed='row_index' if wanted=='column' else 'column_index'
        span='column_span' if wanted=='column' else 'row_span'
        covered={i for c in headers for i in range(c[varying],c[varying]+c.get(span,1))}
        if len({c[fixed] for c in headers})!=1 or covered!=indices or len(headers)<2:continue
        # All covered columns/rows must belong to a declared solubility result axis.
        properties=[p for p in result['property_axes'] if p.get('axis')==wanted and
                    (p.get('quantity_kind')=='solubility' or 'solubil' in str(p.get('property_name_raw','')).casefold())]
        if not indices.issubset({i for p in properties for i in p.get('indices',[])}):continue
        old=axis['axis'];axis['axis']=wanted
        audit.append({'condition_axis_index':number,'from_axis':old,'to_axis':wanted,
             'source_cell_ids':refs,'indices_unchanged':True,
             'basis':'unique_raw_header_geometry_agrees_with_explicit_application_scope_and_property_axes'})
    return result,audit

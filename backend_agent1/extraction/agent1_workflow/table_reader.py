"""Read raw cells using fresh structural axes. Never generate/parse measurement numbers."""
from copy import deepcopy
import re
from stage3_completion import surface

def condition_family(name):
    name=re.sub(r'[^a-z]','',str(name).casefold())
    if 'frequency' in name or name in ('freq','testfreq'):return 'frequency'
    if 'solvent' in name:return 'solvent'
    return name

def frequency_property(prop):
    return any(w in str(prop.get('property_name_raw','')).casefold()
        for w in ('dielectr','permittiv','conductiv','impedance','dynamic','storage modulus','loss modulus'))


def matches(axis, cell):
    from subject_scope import permits
    key='row_index' if axis.get('axis')=='row' else 'column_index' if axis.get('axis')=='column' else None
    return bool(key and cell[key] in axis.get('indices',[]) and permits(axis.get('region'),cell))


def covering(cells,row,column):
    found=[c for c in cells if c['row_index']<=row<c['row_index']+c.get('row_span',1)
           and c['column_index']<=column<c['column_index']+c.get('column_span',1)]
    return found[0] if len(found)==1 else None


def interpret(table, response, target_ids, sample_ids):
    for field in ('property_axes','subject_axes','condition_axes','cell_overrides','notes','unresolved'):
        if not isinstance(response.get(field),list):raise ValueError('Invalid table response: '+field)
    cells=table['cells'];by_id={c['cell_id']:c for c in cells};header_refs=set();issues=[]
    for axis in response['property_axes']+response['subject_axes']+response['condition_axes']:
        refs=axis.get('source_cell_ids',[])
        if any(cid not in by_id for cid in refs):issues.append({'reason':'axis_source_reference_invalid','axis':axis})
        for cid in refs:
            if cid not in by_id:continue
            c=by_id[cid]
            if any(axis is a for a in response['condition_axes']) and any(matches(s,c) for s in response['subject_axes']) and any(matches(p,c) for p in response['property_axes']):
                issues.append({'reason':'condition_axis_references_measurement_cell','cell_id':cid})
                continue
            header_refs.add(cid)
    # A solvent matrix describes the solvent in each result-axis label. Its
    # +/- result cells are never solvent conditions on other property columns.
    # Ordinary separate solvent/Tc data columns retain the original lookup.
    matrix_labels={};required_scoped=set();data_axes=set()
    for number,axis in enumerate(response['condition_axes']):
        name=condition_family(axis.get('name_raw'))
        if name not in ('solvent','frequency'):continue
        if name=='frequency':required_scoped.add(number)
        peers=[p for p in response['property_axes'] if p.get('axis')==axis.get('axis')
            and (('solubil' in str(p.get('property_name_raw','')).casefold()) if name=='solvent'
                 else frequency_property(p))
            and set(p.get('indices',[])) & set(axis.get('indices',[]))]
        if not peers:
            if name=='frequency':
                scope=axis.get('applies_to',{})
                headers=[by_id[c] for c in axis.get('source_cell_ids',[]) if c in by_id]
                overlaps=any(p.get('axis')==axis.get('axis') and set(p.get('indices',[]))&set(axis.get('indices',[])) for p in response['property_axes'])
                if axis.get('value_location')=='data_axis' and scope.get('axis') in ('row','column') and scope.get('indices') and not overlaps and headers and all(not any(matches(s,h) for s in response['subject_axes']) and re.search(r'(?i)hz',surface(h['text'])) for h in headers):
                    data_axes.add(number)
                else:issues.append({'reason':'frequency_axis_scope_unverified','axis':axis})
            continue
        required_scoped.add(number)
        labels={};coordinate='row_index' if axis.get('axis')=='row' else 'column_index'
        span='row_span' if coordinate=='row_index' else 'column_span'
        for index in axis.get('indices',[]):
            candidates=[by_id[cid] for cid in axis.get('source_cell_ids',[]) if cid in by_id
                and by_id[cid][coordinate]<=index<by_id[cid][coordinate]+by_id[cid].get(span,1)
                and not any(matches(s,by_id[cid]) for s in response['subject_axes'])]
            unique={c['cell_id']:c for c in candidates}
            if len(unique)!=1:break
            label=next(iter(unique.values()))
            if name=='frequency' and not (re.search(r'\d',label['text'])
                    and re.search(r'(?i)hz',surface(label['text']))):break
            labels[index]=label
        if len(labels)==len(axis.get('indices',[])) and labels:
            matrix_labels[number]=labels
        else:issues.append({'reason':'condition_header_scope_not_unique','axis':axis})
    observations=[];ledger=[]
    overrides={x.get('cell_id'):x for x in response['cell_overrides']}
    for cell in cells:
        cid=cell['cell_id'];value=cell['text']
        if not str(value).strip():ledger.append({'cell_id':cid,'status':'empty_source_cell'});continue
        properties=[x for x in response['property_axes'] if matches(x,cell)]
        subjects=[x for x in response['subject_axes'] if matches(x,cell)]
        if cid in header_refs:
            ledger.append({'cell_id':cid,'status':'declared_header_or_subject_axis'});continue
        if not properties:
            ledger.append({'cell_id':cid,'status':'source_cell_without_property_axis'});continue
        if not subjects:subjects=[{'sample_id':None,'owner_scope':'unknown','owner_label_raw':None}]
        for prop in properties:
            for subject in subjects:
                meta={**deepcopy(prop),**{k:deepcopy(v) for k,v in subject.items() if k in ('sample_id','owner_label_raw','owner_scope')}}
                conditions=deepcopy(prop.get('conditions',[]))+deepcopy(subject.get('conditions',[]))
                # A loss criterion is inherited only from a declared property
                # header spatially covering this Td column, never arbitrary text.
                if str(prop.get('target_id','')).endswith(':thermal_decomposition_temperature'):
                    known_loss=any(any(word in re.sub(r'[^a-z]','',str(c.get('name_raw','')).casefold())
                        for word in ('weightloss','massloss','wtloss')) for c in conditions)
                    criteria=[]
                    for source_id in prop.get('source_cell_ids',[]):
                        header=by_id.get(source_id)
                        if not header or header['row_index']>=cell['row_index']:continue
                        if not header['column_index']<=cell['column_index']<header['column_index']+header.get('column_span',1):continue
                        match=re.search(r'(?i)(\d[\d\s.,]*\s*(?:(?:wt|weight|mass)\s*)?%\s*(?:(?:wt|weight|mass)\s*)?loss)\b',header['text'])
                        if match:criteria.append((header,match.group(1)))
                    unique_criteria={h['cell_id']:(h,value) for h,value in criteria}
                    if not known_loss and len(unique_criteria)==1:
                        header,raw=next(iter(unique_criteria.values()))
                        conditions.append({'name_raw':'weight_loss','value_raw':raw,'unit_raw':'%',
                            'source_cell_ids':[header['cell_id']],
                            'inheritance':'exact_raw_span_from_declared_covering_header'})
                    elif not known_loss and len(unique_criteria)>1:
                        issues.append({'reason':'loss_header_scope_not_unique','cell_id':cid})
                for number,axis in enumerate(response['condition_axes']):
                    scope=axis.get('applies_to')
                    if scope is not None and (not isinstance(scope,dict) or not matches(scope,cell)):continue
                    if number in matrix_labels:
                        name=condition_family(axis.get('name_raw'))
                        applies=('solubil' in str(prop.get('property_name_raw','')).casefold()) if name=='solvent' else frequency_property(prop)
                        if matches(axis,cell) and applies:
                            coordinate='row_index' if axis.get('axis')=='row' else 'column_index'
                            source=matrix_labels[number][cell[coordinate]]
                            conditions.append({'name_raw':axis.get('name_raw'),'value_raw':source['text'],
                                'unit_raw':axis.get('unit_raw'),'source_cell_ids':[source['cell_id']]})
                        continue
                    if number in required_scoped and number not in data_axes:continue
                    for index in axis.get('indices',[]):
                        source=covering(cells,cell['row_index'],index) if axis.get('axis')=='column' else covering(cells,index,cell['column_index'])
                        if source and source['cell_id'] != cid:
                            conditions.append({'name_raw':axis.get('name_raw'),'value_raw':source['text'],
                                'unit_raw':axis.get('unit_raw'),'source_cell_ids':[source['cell_id']]})
                if cid in overrides:
                    override=overrides[cid]
                    # Explicit null override is retained, never interpreted as "use first".
                    for field in ('sample_id','target_id','value_role'):
                        if field in override:meta[field]=override[field]
                    conditions+=deepcopy(override.get('conditions',[]))
                if meta.get('target_id') not in target_ids:meta['target_id']=None
                if meta.get('sample_id') not in sample_ids:meta['sample_id']=None
                observations.append({'role_handoff':{k:deepcopy(prop.get(k)) for k in ('value_role','role_detail','role_reason_raw','role_evidence_refs','method_reporting','method_reporting_reason_raw')},'target_id':meta.get('target_id'),'is_target':meta.get('is_target',True),
                    'property_name_raw':meta.get('property_name_raw'),'subtype_raw':meta.get('subtype_raw'),
                    'sample_id':meta.get('sample_id'),'owner_label_raw':meta.get('owner_label_raw'),
                    'owner_scope':meta.get('owner_scope','unknown'),'sample_ids':[],
                    'value_raw':value,'unit_raw':meta.get('unit_raw'),'value_role':meta.get('value_role','unknown'),
                    'conditions':conditions,'method_raw':meta.get('method_raw'),'source_block_id':table['table_id'],
                    'source_cell_id':cid,'quote':value,'qualifiers_raw':[],
                    'property_source_cell_ids':prop.get('source_cell_ids',[]),
                    'unit_source_cell_ids':prop.get('unit_source_cell_ids',[]),
                    'legend_raw':prop.get('legend_raw'),'table_id':table['table_id']})
        ledger.append({'cell_id':cid,'status':'raw_value_read','candidate_count':len(properties)*len(subjects)})
    from declared_facts import retain_declared
    recovered,declared_audit=retain_declared(table,response,observations,ledger)
    observations.extend(recovered)
    return observations,{'declared_fact_coverage':declared_audit,'cell_ledger':ledger,'issues':issues,'unresolved':response['unresolved'],
        'all_source_cells_accounted_for':len(ledger)==len(cells),'raw_values_generated_by_model':False}

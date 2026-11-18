"""Bind qualifiers to their own legend clause, preserving unsupported additions separately."""
from copy import deepcopy
import re
from evidence_text import view,original_span

POLICY='symbol_clause_qualifier_scope.v2'

def normalize(task,response):
    from mapping_contract import sources_for,refs_valid,symbol_key
    data=deepcopy(response);sources=sources_for(task);tid=task['table_id'];audit=[]
    for rule in data.get('symbol_rules',[]):
        if not isinstance(rule,dict) or rule.get('legend_scope_policy')==POLICY:continue
        if not refs_valid(rule.get('evidence_refs'),sources,tid,True):continue
        symbol=symbol_key(rule.get('symbol_raw'));clauses={};legend_ids=set()
        for ref in rule['evidence_refs']:
            sid=ref.get('source_id');source=sources.get(sid,{})
            if source.get('kind') not in ('pdf_legend_visual_transcription','ocr_footnote'):continue
            legend_ids.add(sid)
            for segment in re.split(r'[;\n]',source.get('text','')):
                match_text=symbol_key(segment)
                if re.match(r'^'+re.escape(symbol)+r'(?=\s|[,=:])',match_text):
                    key=view(match_text)[0].rstrip('.')
                    clauses.setdefault(key,{'clause_raw':segment.strip(),'source_ids':[]})['source_ids'].append(sid)
        if len(clauses)!=1:continue
        bound=next(iter(clauses.values()));clause=bound['clause_raw']
        kept=[];unverified=[]
        for condition in rule.get('conditions',[]):
            if not isinstance(condition,dict):kept.append(condition);continue
            name=str(condition.get('name_raw','')).casefold()
            is_temperature=any(w in name for w in ('temperature','heating','heated'))
            value=condition.get('value_raw')
            independent_method=False
            for ref in condition.get('evidence_refs',[]):
                sid=ref.get('source_id');source=sources.get(sid,{})
                if sid not in legend_ids and source and original_span(source.get('text',''),ref.get('quote')) and original_span(ref.get('quote',''),str(value)):
                    independent_method=True
            supported=original_span(clause,str(value)) is not None
            if is_temperature and value is not None and not supported and not independent_method:
                unverified.append({'condition':deepcopy(condition),'reason':'temperature_not_supported_by_own_symbol_clause',
                    'bound_clause':deepcopy(bound),'status':'needs_review'})
            else:kept.append(condition)
        if not unverified:continue
        rule['conditions_declared_raw']=deepcopy(rule.get('conditions',[]))
        rule['conditions']=kept
        rule['supplementary_unverified_conditions']=unverified
        rule['bound_legend_clause']=bound;rule['legend_scope_policy']=POLICY
        if rule.get('regime')=='heated_alternative' and re.search(r'\bheat(?:ed|ing)?\b',clause,re.I) and not re.search(r'\bor\b',clause,re.I):
            rule['regime_declared_raw']=rule['regime'];rule['regime']='heated'
            rule['regime_scope_basis']='literal_heating_clause_preserved; unsupported_temperature_alternative_held_separately'
        audit.append({'rule_id':rule.get('rule_id'),'symbol_raw':rule.get('symbol_raw'),
            'supplementary_unverified_count':len(unverified),'bound_clause':bound,
            'regime_declared_raw':rule.get('regime_declared_raw',rule.get('regime')),'effective_regime':rule.get('regime'),
            'measurement_values_unchanged':True})
    return data,audit

def annotate_record(row,observation):
    result=deepcopy(row)
    rule=observation.get('symbol_rule') or {}
    extra=rule.get('supplementary_unverified_conditions',[])
    if extra:
        result.setdefault('supplementary_reviews',[]).extend(deepcopy(extra))
        result['supplementary_status']='needs_review'
        result['legend_scope_policy']=POLICY
    return result

def install():
    import run_trial,mapping_contract
    if getattr(run_trial,'legend_scope_installed',False):return
    read_original=run_trial.read_table;record_original=run_trial.observation_record
    def read(task,response,target_ids,sample_ids):
        data,audit=normalize(task,response)
        rows,info=read_original(task,data,target_ids,sample_ids)
        info['legend_scope_adaptations']=audit
        return rows,info
    def record(observation,*args,**kwargs):return annotate_record(record_original(observation,*args,**kwargs),observation)
    run_trial.read_table=read;run_trial.observation_record=record;run_trial.legend_scope_installed=True

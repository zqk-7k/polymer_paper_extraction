"""Actual export -> stable internal directory; no historical identity/model answers."""
from copy import deepcopy
import re
from common import digest
from catalog import norm

# General category routing replaces the former two-name whitelist. Every object
# gets exactly one destination: import, deliberate exclusion, or explicit review.
# polymer_type keeps the frozen schema literals only; the network/restructured
# identity travels on identity_contexts (agent1_category, agent1_role, derived_from).
CATEGORY_ROUTES={'聚合物':{'polymer_type':None},'共混物':{'polymer_type':'polymer_blend'},
                 '网络':{'polymer_type':None}}
DELIBERATE_EXCLUSIONS={'单体':'monomer_intentional_out_of_scope'}
BASE_RELATION=re.compile(r'(?P<label>[^\s，,；;（()]+)\s*[（(]\s*base_polymer\s*[,，]\s*derived_from\s*[)）]')

def stable(prefix,document,identifier):
    return prefix+str(int(digest([document,identifier])[:14],16))

def locate(raw,names,axis):
    exact={norm(s) for s in names if isinstance(s,str) and s.strip()};candidates=[]
    for b in raw['elements']:
        if b.get('type')=='table':
            for c in b.get('table_cells',[]):
                if norm(c['text']) in exact or axis and c['text'].strip()==axis['value_raw']:
                    candidates.append({'block_id':b['block_id'],'page':b.get('page',0),'bbox':b.get('bbox'),
                        'source_type':'table','source_sentence':c['text'],
                        'table_locator':{'table_id':b['block_id'],'cell_id':c['cell_id']}})
        elif b.get('type') in ('text','paragraph'):
            text=b.get('text','')
            if any(len(s)>=2 and re.search(r'(?<![A-Za-z0-9])'+re.escape(s)+r'(?![A-Za-z0-9])',text,re.I) for s in names):
                candidates.append({'block_id':b['block_id'],'page':b.get('page',0),'bbox':b.get('bbox'),
                    'source_type':'text','source_sentence':text,'table_locator':None})
    if not candidates:raise ValueError('No original literal label/composition anchor for imported object')
    candidates.sort(key=lambda p:0 if p['source_type']=='table' and norm(p['source_sentence']) in exact else 1)
    return candidates

def page_context(raw,obj):
    """Page references locate context only; never claim they verify an identity label."""
    pages={int(p)-1 for p in re.findall(r'page\s*:\s*(\d+)',str(obj.get('来源页') or ''))}
    blocks=[b for b in raw['elements'] if b.get('page') in pages and b.get('type') in ('text','paragraph') and b.get('text')]
    if not blocks:raise ValueError('No original literal anchor or explicit source-page context for imported identity')
    return [{'block_id':b['block_id'],'page':b['page'],'bbox':b.get('bbox'),'source_type':'text',
             'source_sentence':b['text'],'table_locator':None} for b in blocks]

def derive_network_relations(objects,contexts):
    """Resolve base-polymer links for imported networks from composition text only.

    A unique label match against other imported objects yields a structured
    derived_from; anything ambiguous stays relation_pending_review with the raw
    text retained. No relation is guessed from names or categories alone.
    """
    imported={c['agent_id']:c for c in contexts}
    by_label={}
    for obj in objects:
        if obj['ID'] not in imported or obj.get('类别')!='聚合物':continue
        names=[obj.get('标签')]+[s.strip() for s in str(obj.get('来源名') or '').splitlines() if s.strip()]
        for name in names:
            if isinstance(name,str) and name.strip():by_label.setdefault(name.strip(),set()).add(obj['ID'])
    for context in contexts:
        if context.get('agent1_category')!='网络':continue
        text=str(context.get('raw_composition') or '')
        relations=[]
        for match in BASE_RELATION.finditer(text):
            label=match['label'].strip();candidates=by_label.get(label,set())
            if len(candidates)==1 and next(iter(candidates)) in imported:
                base=imported[next(iter(candidates))]
                relations.append({'base_agent_id':base['agent_id'],'base_entity_id':base['entity_id'],
                    'base_sample_id':base['sample_id'],'base_label':label,
                    'relation':'chemically_derived_network_from_base_polymer',
                    'basis':'unique_label_match_in_composition_axis_text','raw_text':match.group(0)})
            else:
                relations.append({'base_label':label,'relation':'relation_pending_review',
                    'basis':'no_unique_imported_base_object_label_match','raw_text':match.group(0),
                    'candidate_base_agent_ids':sorted(candidates)})
        context['derived_from']=relations

def convert(export,raw):
    document=raw['document_id'];paper=str(export.get('paper',''))
    if paper not in (document,document.removeprefix('reference_no_')):raise ValueError('Export/article document mismatch')
    objects=export.get('major_objects')
    if not isinstance(objects,list) or not objects:raise ValueError('Missing major_objects')
    ids=[o.get('ID') for o in objects]
    if any(not isinstance(i,str) or not i for i in ids) or len(ids)!=len(set(ids)):raise ValueError('Missing/duplicate agent1 object ID')
    entities=[];samples=[];contexts=[];excluded=[];anchors=[]
    for obj in objects:
        category=obj.get('类别')
        if category in CATEGORY_ROUTES:
            ptype=CATEGORY_ROUTES[category]['polymer_type']
        elif category in DELIBERATE_EXCLUSIONS:
            excluded.append({'object':deepcopy(obj),'reason':DELIBERATE_EXCLUSIONS[category],
                             'requires_category_review':False});continue
        else:
            excluded.append({'object':deepcopy(obj),'reason':'unknown_category_requires_review',
                             'requires_category_review':True});continue
        aid=obj['ID'];label=obj.get('标签')
        if not isinstance(label,str) or not label.strip():raise ValueError('Missing object label')
        names=list(dict.fromkeys([label]+[s.strip() for s in str(obj.get('来源名') or '').splitlines() if s.strip()]))
        axis=None;match=re.search(r'(?P<name>[A-Za-z][A-Za-z0-9_]*)\s*=\s*(?P<value>[0-9]+(?:\.[0-9]+)?)',label)
        if match:axis={'name_raw':match['name'],'value_raw':match['value'],'unit_raw':None,'interpretation':'literal_declared_axis_no_conversion'}
        try:proofs=locate(raw,names,axis);anchor_status='literal_label_or_declared_axis'
        except ValueError:proofs=page_context(raw,obj);anchor_status='page_context_only_identity_not_verified'
        proof=proofs[0]
        if axis:
            cells=[p for p in proofs if p['source_type']=='table' and p['source_sentence'].strip()==axis['value_raw']]
            if cells:axis['evidence']={'table_locator':{**cells[0]['table_locator'],'cell_value':cells[0]['source_sentence']}}
        eid=stable('pe',document,aid);sid=stable('s',document,aid)
        # Entities follow the frozen Stage2 schema strictly (no extra keys);
        # category and role travel on identity_contexts, which are free-form.
        entities.append({'entity_id':eid,'polymer_name':label,'polymer_type':ptype,'copolymer_type':None,'variant_of':None,
            'representation_status':'expert_review_required','structural_features':[],'source_names':names,
            'resolved_from_mentions':['agent1:'+aid],'evidence':proof,'source_image_refs':[],'confidence':None})
        samples.append({'sample_id':sid,'sample_kind':'unspecified','refers_to_entity':eid,'polymer_name':label,
            'polymer_type':ptype,'copolymer_type':None,'material_type':None,'sample_label_raw':label,
            'state_description':None,'intended_use':[],'evidence':proof,'confidence':None,
            'agent1_category':category})
        contexts.append({'identity_key':document+':'+aid,'agent_id':aid,'agent_label':label,'sample_id':sid,'entity_id':eid,
            'composition_axis':axis,'raw_composition':obj.get('组分与投料比'),'raw_preparation':obj.get('制备方式'),
            'unknowns':obj.get('未知事项'),'independent_batch_confirmed':False,'agent1_original_object':deepcopy(obj),
            'identity_source_status':anchor_status,'source_page_raw':obj.get('来源页'),
            'agent1_category':category,'agent1_role':obj.get('角色'),'derived_from':[],
            'directory_source':'user_supplied_agent1_identity_not_reidentified_here'})
        anchors.append({'agent_id':aid,'sample_id':sid,'evidence_candidates':proofs,'literal_anchor_not_chemical_quality_review':True,
                        'identity_source_status':anchor_status,'source_page_raw':obj.get('来源页')})
    derive_network_relations(objects,contexts)
    if not samples:raise ValueError('No in-scope polymer objects')
    # Coverage invariant: every exported object has exactly one destination.
    imported_ids={c['agent_id'] for c in contexts};excluded_ids={x['object']['ID'] for x in excluded}
    assert imported_ids.isdisjoint(excluded_ids)
    assert imported_ids|excluded_ids=={o['ID'] for o in objects},'Silent object loss in directory routing'
    assert len({s['sample_id'] for s in samples})==len(samples)
    stage2={'document_id':document,'polymer_entities':entities,'unresolved_mention_ids':[],
        'provenance':{'source':'actual_agent1_export','input_hash':digest(export),'inference_calls':0},'warnings':[]}
    seed={'document_id':document,'samples':samples,'identity_contexts':contexts,'process_steps':[],'protocol_contexts':[],'warnings':[]}
    return stage2,seed,{'identities':contexts,'excluded_objects':excluded,'anchors':anchors,'all_original_objects_preserved':True,
        'category_routing':{'imported':sorted(imported_ids),'deliberate_exclusions':sorted(excluded_ids-{x['object']['ID'] for x in excluded if x.get('requires_category_review')}),
            'unknown_category_review':sorted(x['object']['ID'] for x in excluded if x.get('requires_category_review')),
            'network_relations':{c['agent_id']:c['derived_from'] for c in contexts if c.get('agent1_category')=='网络'}}}

def envelope(stage2,seed,source):
    entities={e['entity_id'] for e in stage2['polymer_entities']};samples=seed['samples']
    assert len({s['sample_id'] for s in samples})==len(samples)
    assert all(s.get('refers_to_entity') is None or s['refers_to_entity'] in entities for s in samples)
    return {'schema':'directory_contract.v1','document_id':stage2['document_id'],'source':source,
        'entities':deepcopy(stage2['polymer_entities']),'samples':deepcopy(samples),
        'identity_contexts':deepcopy(seed.get('identity_contexts',[])),'raw_values_unchanged':True}

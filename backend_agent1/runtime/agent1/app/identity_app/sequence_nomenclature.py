"""Opt-in source sequence/ordered-block rules; source claims are model declarations.

No product graph, random sequence, junction or preferred name is inferred here.
Existing Kernel/NamingService checks still verify the named source/block inputs.
"""
from copy import deepcopy

CONTRACT = 'identity-evidence-nomenclature/1.5'
RULE = 'https://iupac.qmul.ac.uk/BriefGuide/polymer.html#3.2'
CONNECTIVES = {'unspecified':'co', 'alternating':'alt', 'statistical':'stat', 'random':'ran'}


def evidence_errors(evidence, descriptor, refs):
    if not isinstance(evidence,dict):return 'EXPLICIT_SEQUENCE_SOURCE_EVIDENCE_REQUIRED'
    bound=evidence.get('source_refs')
    if (evidence.get('status')!='source_reported' or evidence.get('descriptor')!=descriptor
            or not isinstance(evidence.get('as_reported'),str) or not evidence['as_reported'].strip()
            or not isinstance(evidence.get('reason'),str) or not evidence['reason'].strip()
            or not isinstance(bound,list) or not bound or not all(isinstance(x,str) for x in bound)
            or not set(bound).issubset(set(refs))):
        return 'EXPLICIT_SEQUENCE_SOURCE_EVIDENCE_REQUIRED'
    return None


def source_sequence(declaration, material, names):
    seq=declaration.get('sequence','unspecified')
    if not isinstance(seq,str) or seq not in CONNECTIVES:return {'reason_code':'SEQUENCE_PROFILE_NOT_ENABLED'}
    known=(material.get('identity_attributes') or {}).get('sequence')
    if isinstance(known,str) and known in CONNECTIVES and known!='unspecified' and known!=seq:
        return {'reason_code':'DECLARED_SEQUENCE_MUST_BE_PRESERVED'}
    if seq=='unspecified':return {'connective':'co','sequence':'unspecified'}
    if len(set(names))<2 or (seq=='alternating' and len(names)!=2):
        return {'reason_code':'DISTINCT_COPOLYMER_SOURCES_REQUIRED'}
    error=evidence_errors(declaration.get('sequence_evidence'),seq,declaration.get('source_refs',[]))
    if error:return {'reason_code':error}
    if seq in ('random','statistical') and (material.get('constitution')
            or (material.get('structure_expression') or {}).get('kind')=='ideal_repeat'):
        return {'reason_code':'NONREGULAR_SEQUENCE_IS_NOT_SINGLE_IDEAL_REPEAT'}
    return {'connective':CONNECTIVES[seq],'sequence':seq,
            'evidence':deepcopy(declaration['sequence_evidence']),
            'source_interpretation':'SAME_PRIMARY_MODEL_DECLARATION_NOT_INDEPENDENT_VERIFICATION'}


def block_name(material,candidate,declaration,child):
    def fail(reason):return {'reason_code':reason}
    if (material.get('kind') not in ('polymer','prepolymer') or declaration.get('combination')!='covalent'
            or material.get('constitution') or (material.get('structure_expression') or {}).get('kind')
            not in ('source_only','local_connectivity')):
        return fail('BLOCK_COPOLYMER_IS_NOT_PHYSICAL_ASSEMBLY_OR_SINGLE_REPEAT')
    error=evidence_errors(declaration.get('block_evidence'),'block',declaration.get('source_refs',[]))
    if error:return fail(error)
    blocks=declaration.get('blocks')
    if not isinstance(blocks,list) or len(blocks)<2 or any(not isinstance(x,dict) for x in blocks):
        return fail('ORDERED_BLOCK_OCCURRENCES_REQUIRED')
    occurrences=[x.get('occurrence_id') for x in blocks]
    if (any(not isinstance(x,str) or not x.strip() for x in occurrences)
            or len(set(occurrences))!=len(occurrences)):
        return fail('UNIQUE_BLOCK_OCCURRENCE_IDS_REQUIRED')
    ids=[x.get('material_id') for x in blocks]
    if any(not isinstance(x,str) or x not in candidate['materials'] or x==material['id'] for x in ids):
        return fail('BLOCK_MATERIAL_BINDING_REQUIRED')
    if len(set(ids))<2:return fail('DISTINCT_POLYMER_BLOCKS_REQUIRED')
    names=[]; assessed=[]; hypotheses=[]
    for block,mid in zip(blocks,ids):
        refs=block.get('source_refs')
        if not isinstance(refs,list) or not refs or not all(isinstance(x,str) for x in refs) or not set(refs).issubset(set(declaration['source_refs'])):
            return fail('BLOCK_OCCURRENCE_SOURCE_BINDING_REQUIRED')
        links=[x for x in material.get('components',[]) if x.get('material_id')==mid]
        if not links or any(x.get('relation')!='covalent_block_segment' for x in links):
            return fail('COVALENT_BLOCK_COMPONENT_BINDING_REQUIRED')
        if any(r.get('from_material_id')==mid and r.get('to_material_id')==material['id']
               and r.get('type') in ('physical_blend_component','formulation_component','graft_sidechain_of')
               for r in candidate.get('relations',[])):
            return fail('BLOCK_RELATION_CONFLICT')
        other=candidate['materials'][mid]; a=child(mid)
        if other.get('kind') not in ('polymer','prepolymer') or not a or not a.get('formal_name') or not a.get('primary_matches_display'):
            return fail('POLYMER_BLOCK_NAME_NOT_READY')
        names.append(a['formal_name']);assessed.append({'occurrence_id':block['occurrence_id'],
            'material_id':mid,'name':a['formal_name'],'source_refs':deepcopy(refs),'assessment':a})
        for h in a.get('hypotheses',[]):
            if h not in hypotheses:hypotheses.append(deepcopy(h))
    text='-block-'.join(names)
    return {'status':'SOURCE_BLOCK_SUPPORTED','primary':text,'formal_name':text,
            'scope':'reported_covalent_block_architecture_without_unique_whole_cru',
            'block_occurrences':assessed,'hypotheses':hypotheses,
            'block_evidence':deepcopy(declaration['block_evidence']),
            'whole_product_constitution_inferred':False,
            'checks':[{'rule':RULE,'status':'PASS','rule_scope':'ordered already-named polymer blocks and explicit covalent source declaration; junctions not inferred'}],
            'next_steps':['按原文保留各块长度分布、连接位点和端基；嵌段来源名不证明唯一整体重复单元或优选名称。']}

"""Name/facts -> source graphs -> evidence-conditioned units -> naming.
No formation rule is selected by a catalog answer or by a test expectation.
The caller supplies formation facts. Nonperiodic mixtures never get a fake CRU.
"""
from copy import deepcopy
from .common import fail
from .reactions import derive
from .naming import name_from_unit
from .architecture import compile_explicit_periodic_sequence


def from_parsed(parsed,inputs):
    leaves=parsed.get('components',[]);formation=inputs.get('formation');local=inputs.get('formation_by_occurrence',{})
    out={'status':'NEEDS_DETAILS','reason_code':'FORMATION_FACTS_OR_EXPLICIT_UNITS_REQUIRED','product_units':[],
         'exact_material_identity':False,'scope':'evidence_conditioned_constitution'}
    if formation:
        def has_complex_scope(n):
            return n.get('qualifier_dimension')=='topology' or n.get('operator') in ('block','graft','comb','ran','stat','net','blend','ipn','sipn','compl','/') or any(has_complex_scope(c) for c in n.get('children',[]))
        if has_complex_scope(parsed.get('ast',{})):
            return fail('WHOLE_COMPLEX_ARCHITECTURE_NEEDS_LOCAL_UNIT_FACTS','NEEDS_DETAILS')
        sources=[c for c in leaves if c['kind']=='source']
        if len(sources)!=len(leaves) or not sources:return fail('ALL_NAMING_SOURCES_MUST_BE_RESOLVED','PARTIAL')
        args=deepcopy(formation)
        if 'monomer_smiles' in args or 'reactants_smiles' in args:return fail('FORMATION_GRAPH_MUST_COME_FROM_CURRENT_RESOLVED_SOURCES','INVALID')
        if len(sources)==1:args['monomer_smiles']=sources[0]['molecule']['isomeric_smiles']
        elif len(sources)==2 and args.get('reaction_class') in ('condensation_ester','condensation_amide','polyurethane','imidization'):
            args['reactants_smiles']=[x['molecule']['isomeric_smiles'] for x in sources]
        else:return fail('MULTICOMPONENT_FORMATION_NEEDS_EXPLICIT_LOCAL_RULES','NEEDS_DETAILS')
        result=derive(args)
        if result['status']!='PARSED':return result
        result['source_occurrences']=[x['occurrence_id'] for x in sources];result['naming']=name_from_unit(result['repeat_smiles'])
        return {'status':'PARSED','product_units':[result],'periodic':result['periodic'],'naming':result['naming'],'evidence':formation.get('evidence',formation.get('evidence_kind')),
                'scope':'evidence_conditioned_constitution','exact_material_identity':False}
    if local:
        if not isinstance(local,dict):return fail('LOCAL_FORMATION_MAP_REQUIRED','INVALID')
        ids={c['occurrence_id']:c for c in leaves};results=[]
        for ident,facts in local.items():
            if ident not in ids or ids[ident]['kind']!='source':return fail('UNKNOWN_OR_NON_SOURCE_FORMATION_REFERENCE','INVALID',occurrence_id=ident)
            args={**facts,'monomer_smiles':ids[ident]['molecule']['isomeric_smiles']}
            if 'reactants_smiles' in args:return fail('LOCAL_MULTI_SOURCE_RULE_REQUIRES_EXPLICIT_BINDING','INVALID')
            r=derive(args);results.append({'occurrence_id':ident,'result':r})
        return {'status':'PARSED' if all(x['result']['status']=='PARSED' for x in results) else 'PARTIAL','product_units':results,
                'uncompiled_occurrences':sorted(set(ids)-set(local)),'reason_code':'WHOLE_NONPERIODIC_GRAPH_NOT_ASSERTED','whole_constitution_key':None,'exact_material_identity':False}
    return out

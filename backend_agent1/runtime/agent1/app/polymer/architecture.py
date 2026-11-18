"""Occurrence graph and typed symbolic constraints, separate from atom graphs."""
from __future__ import annotations
from copy import deepcopy
from .common import key,stable_json,fail
from .validation import validate_composition
from .periodic import assemble,canonicalize_unit
from .chemistry import canonicalize


def compile_architecture(parsed):
    ast=parsed.get('ast')
    if not ast:return fail('NO_NAME_AST','PARTIAL')
    nodes=[];edges=[];constraints=[];missing=[]
    def rec(n):
        ident=n['occurrence_id'];kind=n['kind'];entry={'id':ident,'kind':kind,'label':n['raw']}
        for k in ['operator','qualifier','alpha','omega','class']:
            if k in n:entry[k]=n[k]
        if kind=='source':entry['source_molecule_key']=n['molecule']['molecule_key'];entry['source_smiles']=n['molecule']['isomeric_smiles'];entry['product_graph_known']=False
        if kind=='unit':entry['unit_smiles']=n['unit']['unit_smiles'];entry['unit_key']=n['unit']['periodic']['periodic_graph_key']
        if kind=='opaque':missing.append({'node_id':ident,'field':'chemical_graph','reason':'UNRESOLVED_NAME'})
        nodes.append(entry);op=n.get('operator')
        for i,c in enumerate(n.get('children',[])):
            role='component'
            if op in ('graft','comb'):role='backbone' if i==0 else 'sidechain'
            elif op=='block':role='block_occurrence'
            elif op=='sipn':role='network_component' if i==0 else 'linear_component'
            elif op=='/':role='constitutional_unit_option'
            elif kind=='source_pool':role='source_alternative'
            edges.append({'parent':ident,'child':c['occurrence_id'],'role':role,'ordinal':i});rec(c)
        if kind=='source_pool':constraints.append({'node_id':ident,'kind':'source_pool','sequence_not_invented':True,'equal_fractions_assumed':False,'actual_monomer_use_confirmed':False})
        if op:
            constraints.append({'node_id':ident,'kind':op,'child_order_retained':op not in ('co','stat','ran','blend','ipn','compl'),
                'sequence_not_invented':op in ('co','stat','ran','/'),'junction_atoms_known':False})
        if n.get('qualifier_dimension')=='topology':missing.append({'node_id':ident,'field':'topology_edges_or_arm_count','reason':'NAME_QUALIFIER_IS_NOT_EXPLICIT_GRAPH'})
        if op in ('graft','comb','net'):missing.append({'node_id':ident,'field':'junction_atom_sites','reason':'NOT_REPORTED'})
    rec(ast)
    return {'status':'PARSED' if parsed['status']=='PARSED' else 'PARTIAL','scope':'typed_symbolic_architecture',
            'nodes':nodes,'edges':edges,'constraints':constraints,'missing':missing,
            'graph_is':'DESCRIPTION_GRAPH_NOT_ATOMISTIC_MATERIAL','exact_material_identity':False}


def validate_structured(tree):
    """Validate supplied JSON architecture with explicit roles, never invent arms.
    Supported operators describe constraints; atomistic compilation is separate.
    """
    supported={'unit','source','block','graft','co','stat','ran','alt','per','star','comb','brush','branch','cyclo','net','blend','ipn','sipn','compl'}
    ids=set();errors=[];unknown=[];count=0
    def visit(n,depth):
        nonlocal count
        count+=1
        if depth>32 or count>512:errors.append('TREE_LIMIT');return
        if not isinstance(n,dict):errors.append('NODE_MUST_BE_OBJECT');return
        if not isinstance(n.get('id'),str) or not n['id'] or n['id'] in ids:errors.append('MISSING_OR_DUPLICATE_OCCURRENCE_ID');return
        ids.add(n['id']);kind=n.get('kind');children=n.get('children',[])
        if kind not in supported:errors.append('UNSUPPORTED_OPERATOR');return
        if not isinstance(children,list):errors.append('CHILDREN_MUST_BE_ARRAY');return
        if kind in ('unit','source'):
            if children:errors.append('LEAF_HAS_CHILDREN')
            if not n.get('smiles'):unknown.append(n['id'])
            elif kind=='unit':
                r=canonicalize_unit(n['smiles'])
                if r['status']!='PARSED':errors.append('INVALID_OR_OUT_OF_SCOPE_UNIT')
            elif canonicalize(n['smiles'])['status']!='PARSED':errors.append('INVALID_SOURCE_GRAPH')
        elif not children:errors.append('OPERATOR_REQUIRES_COMPONENTS')
        if kind in ('block','graft','comb','brush','blend','ipn','sipn','compl','alt','per') and len(children)<2:errors.append('AT_LEAST_TWO_COMPONENTS_REQUIRED')
        if kind=='star' and n.get('arm_count') is not None:
            if type(n['arm_count']) is not int or n['arm_count']<3 or len(children)!=n['arm_count']:errors.append('STAR_ARM_COUNT_MISMATCH')
        if kind in ('graft','comb','brush') and n.get('backbone_id') not in [x.get('id') for x in children if isinstance(x,dict)]:errors.append('BACKBONE_ROLE_REQUIRED')
        for c in children:visit(c,depth+1)
    visit(tree,0)
    comp=tree.get('composition') if isinstance(tree,dict) else None
    if comp:
        c=validate_composition(comp)
        if c['status']!='PARSED':errors.append(c['reason_code'])
        for ident in comp.get('values',{}) if isinstance(comp.get('values'),dict) else []:
            if ident not in ids:errors.append('COMPOSITION_REF_UNKNOWN')
    return {'status':'INVALID' if errors else ('PARTIAL' if unknown else 'PARSED'),'reason_code':';'.join(sorted(set(errors))) or ('LEAF_STRUCTURE_MISSING' if unknown else None),
            'validated_tree':deepcopy(tree),'node_count':len(ids),'unknown_nodes':unknown,'scope':'explicit_symbolic_architecture','exact_material_identity':False}


def compare_descriptions(parser,left,right):
    a=parser.parse(left);b=parser.parse(right)
    if a['status']!='PARSED' or b['status']!='PARSED':return fail('PARTIAL_DESCRIPTION','PARTIAL',relation='UNRESOLVED',left=a,right=b)
    x=a['semantic_projection']['descriptor'];y=b['semantic_projection']['descriptor']
    def compatible(u,v):
        if u==v:return 'EQUAL'
        if not isinstance(u,dict) or not isinstance(v,dict):return 'DIFFERENT'
        if set(u)-{'operator','children'}!=set(v)-{'operator','children'}:return 'DIFFERENT'
        if any(u.get(k)!=v.get(k) for k in set(u)-{'operator','children'}):return 'DIFFERENT'
        cu=u.get('children',[]);cv=v.get('children',[])
        if len(cu)!=len(cv):return 'DIFFERENT'
        rels=[compatible(i,j) for i,j in zip(cu,cv)]
        rank={'ran':0,'stat':1,'co':2}
        opu=u.get('operator');opv=v.get('operator')
        if opu!=opv:
            if opu not in rank or opv not in rank:return 'DIFFERENT'
            rels.append('LEFT_NARROWER' if rank[opu]<rank[opv] else 'RIGHT_NARROWER')
        dirs=set(rels)-{'EQUAL'}
        return next(iter(dirs)) if len(dirs)==1 else ('EQUAL' if not dirs else 'DIFFERENT')
    r=compatible(x,y)
    return {'status':'PARSED','relation':{'EQUAL':'SAME_DESCRIPTION_CANDIDATE','DIFFERENT':'DIFFERENT_DESCRIPTIONS_NOT_GENERAL_NONISOMORPHISM'}.get(r,r),
            'scope':'described_source_and_architecture','left':a,'right':b,'exact_material_identity':False}


def compile_explicit_periodic_sequence(inputs):
    """Only an explicitly periodic or alternating list of ported CUs gets one CRU.
    Blocks with unspecified lengths, ran/stat/co and networks never get a
    fictional deterministic concatenation masquerading as an infinite chain.
    """
    kind=inputs.get('sequence');units=inputs.get('units');evidence=inputs.get('evidence')
    if kind not in ('alt','per'):return fail('NONPERIODIC_SEQUENCE_HAS_NO_UNIQUE_CRU','NEEDS_DETAILS')
    if not evidence:return fail('PERIODIC_CONNECTION_EVIDENCE_REQUIRED','NEEDS_DETAILS')
    if not isinstance(units,list) or len(units)<2:return fail('EXPLICIT_UNIT_LIST_REQUIRED','INVALID')
    if not inputs.get('orientation_explicit'):return fail('UNIT_PORT_ORIENTATIONS_REQUIRED','NEEDS_DETAILS')
    try:
        s=assemble(units);p=canonicalize_unit(s)
        return {'status':p['status'],'assembled_repeat_smiles':s,'periodic':p,'evidence':evidence,'scope':'specified_periodic_constitution','exact_material_identity':False}
    except (ValueError,RuntimeError) as exc:return fail(str(exc),'INVALID')

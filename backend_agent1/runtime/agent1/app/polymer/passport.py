"""Frozen, scoped polymer passports (0.6).

The description key is not a universal material identifier. Rendering a frozen
passport does not call a registry, a model, OPSIN, a catalog, or a graph namer.
Hashes detect content changes; they are NOT signatures or evidence of truth.
"""
from __future__ import annotations
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from functools import lru_cache

from .common import key, stable_json, fail
from .chemistry import canonicalize
from .naming import name_from_unit, emit_subunit_name
from .periodic import canonicalize_unit

SCHEMA = 'polymer-passport/0.6'
POLICY = 'description-canonicalization/0.6.1'
NAMING = 'frozen-name-candidate/0.6.1'
NAMING07 = 'frozen-name-candidate/0.7.0'
SCHEMA07 = 'polymer-passport/0.7'
NAMING09 = 'frozen-name-candidate/0.9.0'
SCHEMA09 = 'polymer-passport/0.9'
STATUSES = {'specified','not_reported','ambiguous','conflicting','not_applicable'}
OPERATORS = {'co','stat','ran','alt','per','block','graft','blend','comb','ipn','sipn','compl','net'}
ATTRS = {'tacticity','repeat_count','number_average_molar_mass','end_groups','sample_label'}
# Explicit display policy, not a claim that all these labels are preferred names.
DISPLAY = {
 'C=C':'ethene','C=CC':'propene','C=Cc1ccccc1':'styrene','C=CC#N':'acrylonitrile',
 'C=CC=C':'buta-1,3-diene','C=C(C)C=C':'2-methylbuta-1,3-diene',
 'C=CC(=O)O':'acrylic acid','C=C(C)C(=O)OC':'methyl methacrylate',
 'C=CC(=O)OC':'methyl acrylate','C1CO1':'oxirane','OCCO':'ethane-1,2-diol',
 'O=C(O)c1ccc(C(=O)O)cc1':'terephthalic acid',
 'O=C(O)c1cccc(C(=O)O)c1':'isophthalic acid',
}
DISPLAY_BY_GRAPH = {canonicalize(s)['molecule_key']:n for s,n in DISPLAY.items()
                    if canonicalize(s)['status']=='PARSED'}


class PassportError(ValueError):
    pass


def decimal_text(value):
    if isinstance(value,bool):
        raise PassportError('BOOLEAN_IS_NOT_A_QUANTITY')
    try:
        d=Decimal(str(value))
    except (InvalidOperation,ValueError,TypeError):
        raise PassportError('INVALID_DECIMAL')
    if not d.is_finite():
        raise PassportError('NONFINITE_QUANTITY')
    if len(str(d))>100:
        raise PassportError('QUANTITY_SIZE_LIMIT')
    return '0' if d==0 else format(d.normalize(),'f')


def field(value=None, status=None, support='source_explicit'):
    status=status or ('not_reported' if value is None else 'specified')
    return {'knowledge_status':status,'value':value,
            'support_type':support if status=='specified' else None,
            'mapping_status':'mapped' if status=='specified' else 'unprocessed',
            'validation_status':'pass_at_scope' if status=='specified' else 'not_run'}


def _display_labels(registry):
    """The full frozen seed snapshot, not only aliases observed in this input."""
    generation=registry.generation
    old=getattr(registry,'_passport_labels',None)
    if old and old[0]==generation:
        return old[1],old[2]
    candidates={}
    for b in registry.all_bindings():
        if not b['active']: continue
        g=canonicalize(b['smiles'])
        if g['status']=='PARSED':
            candidates.setdefault(g['molecule_key'],[]).append(b['alias'])
    labels={g:DISPLAY_BY_GRAPH.get(g,sorted(set(ns))[0]) for g,ns in candidates.items()}
    labels.update(DISPLAY_BY_GRAPH)
    snapshot=registry.snapshot()['snapshot_key']
    registry._passport_labels=(generation,labels,snapshot)
    return labels,snapshot



@lru_cache(maxsize=1)
def _generated_labels_v07():
    from .common import ROOT
    content=json.loads((ROOT/'data/display_lexicon_v07.json').read_text(encoding='utf-8'))
    if content['lexicon_key']!=key('display-lexicon/0.7',content['entries']):
        raise PassportError('GENERATED_LEXICON_CHECKSUM_MISMATCH')
    labels={r['graph_key']:r['label'] for r in content['entries']}
    # The frozen generated lexicon may have been built with a different
    # RDKit patch version than the current runtime.  Keep its checksum and
    # original graph keys, but add a deterministic canonical-SMILES alias so
    # display lookup remains independent of catalog seed graph-key versions.
    for r in content['entries']:
        parsed=canonicalize(r.get('smiles',''))
        if parsed.get('status')=='PARSED':
            labels.setdefault(parsed['molecule_key'],r['label'])
    return labels,content['lexicon_key']

def _unwrap(n):
    while n.get('kind')=='group' and len(n.get('children',[]))==1:
        n=n['children'][0]
    return n


def _leaves(n):
    if not n.get('children'):
        yield n
    for c in n.get('children',[]):
        yield from _leaves(c)


def _normalize_attr(name, data):
    f=deepcopy(data) if isinstance(data,dict) and 'knowledge_status' in data else field(data)
    if f.get('knowledge_status') not in STATUSES:
        raise PassportError('UNKNOWN_KNOWLEDGE_STATUS')
    if f['knowledge_status']!='specified':
        if f.get('value') is not None:
            raise PassportError('UNKNOWN_FIELD_CANNOT_HAVE_VALUE')
        return field(None,f['knowledge_status'])
    v=f.get('value')
    if v is None: raise PassportError('SPECIFIED_FIELD_REQUIRES_VALUE')
    if name=='repeat_count':
        if isinstance(v,bool) or not str(v).isdigit() or not 1<=int(v)<=1000000000:
            raise PassportError('POSITIVE_INTEGER_REPEAT_COUNT_REQUIRED')
        v=int(v)
    if name=='tacticity':
        if v not in ('isotactic','syndiotactic','atactic'):
            raise PassportError('TACTICITY_OUT_OF_SCOPE')
    if name=='number_average_molar_mass':
        if not isinstance(v,dict) or set(v)!={'value','unit'}:
            raise PassportError('MOLAR_MASS_VALUE_AND_UNIT_REQUIRED')
        factors={'g/mol':Decimal(1),'kg/mol':Decimal(1000)}
        if v['unit'] not in factors: raise PassportError('MOLAR_MASS_UNIT_OUT_OF_SCOPE')
        num=Decimal(decimal_text(v['value']))*factors[v['unit']]
        if num<=0: raise PassportError('POSITIVE_MOLAR_MASS_REQUIRED')
        v={'value':decimal_text(num),'unit':'g/mol'}
    if name=='end_groups':
        from .finite_chains import resolve_end_group
        if not isinstance(v,dict) or set(v)!={'alpha','omega'}:
            raise PassportError('ALPHA_OMEGA_REQUIRED')
        for end in v.values():
            if resolve_end_group(end)['status']!='PARSED':
                raise PassportError('END_GROUP_OUT_OF_SCOPE')
    if name=='sample_label':
        if not isinstance(v,str) or len(v)>300: raise PassportError('INVALID_SAMPLE_LABEL')
    return field(v,support=f.get('support_type') or 'source_explicit')


def _bind_compositions(parsed, inp, registry, issues):
    """Attach fractions before permutation; ABA duplicate sources require IDs."""
    values=inp.get('compositions',[])
    if inp.get('composition') is not None: values=[inp['composition']]+values
    if not isinstance(values,list) or len(values)>16:
        raise PassportError('COMPOSITIONS_ARRAY_REQUIRED')
    leaves=parsed.get('components',[])
    by_id={c['occurrence_id']:c for c in leaves}
    attached={};sets=[];seen={}
    for composition in values:
        if not isinstance(composition,dict): raise PassportError('COMPOSITION_OBJECT_REQUIRED')
        if set(composition)-{'basis','values','completeness','scope'}:
            raise PassportError('UNKNOWN_COMPOSITION_FIELD')
        basis=composition.get('basis')
        if basis not in ('mole_fraction','mass_fraction','feed_mole_fraction','feed_mass_fraction'):
            raise PassportError('COMPOSITION_BASIS_REQUIRED')
        completeness=composition.get('completeness','complete')
        if completeness not in ('complete','partial'): raise PassportError('COMPOSITION_COMPLETENESS_INVALID')
        scope=composition.get('scope','root_source_component_fractions')
        if scope!='root_source_component_fractions':
            raise PassportError('COMPOSITION_SCOPE_NOT_IMPLEMENTED')
        vals=composition.get('values')
        if not isinstance(vals,dict) or not vals: raise PassportError('NAMED_FRACTIONS_REQUIRED')
        bound={}
        for ref,v in vals.items():
            candidates=[by_id[ref]] if ref in by_id else [c for c in leaves if c['raw']==ref]
            if not candidates:
                r=registry.resolve(ref)
                if r.get('molecule_key'):
                    candidates=[c for c in leaves if c.get('molecule',{}).get('molecule_key')==r['molecule_key']]
            if len(candidates)!=1: raise PassportError('COMPOSITION_REFERENCE_UNKNOWN_OR_AMBIGUOUS:'+ref)
            ident=candidates[0]['occurrence_id']
            if ident in bound: raise PassportError('DUPLICATE_COMPOSITION_TARGET')
            frac=decimal_text(v)
            if not 0<=Decimal(frac)<=1: raise PassportError('FRACTION_OUT_OF_RANGE')
            bound[ident]=frac
        total=sum(Decimal(v) for v in bound.values())
        if (completeness=='complete' and abs(total-1)>Decimal('0.00000001')) or total>Decimal('1.00000001'):
            issues.append({'code':'FRACTION_SUM_CONFLICT','severity':'conflicting','basis':basis,'total':decimal_text(total)})
        if completeness=='complete' and set(bound)!=set(by_id):
            issues.append({'code':'COMPLETE_FRACTIONS_MISSING_OCCURRENCES','severity':'partial','basis':basis})
        sets.append({'basis':basis,'scope':scope,'completeness':completeness})
        for ident,v in bound.items():
            pair=(basis,scope,ident)
            if pair in seen and seen[pair]!=v:
                issues.append({'code':'CONFLICTING_COMPOSITION','severity':'conflicting','basis':basis})
            seen[pair]=v
            attached.setdefault(ident,[]).append({'basis':basis,'scope':scope,'value':v})
    return attached,sorted({stable_json(s):s for s in sets}.values(),key=stable_json)


@lru_cache(maxsize=15000)
def _bounded_unit_name(smiles):
    p=canonicalize_unit(smiles)
    if p.get('status')!='PARSED':
        return fail('PERIODIC_GRAPH_OUTSIDE_FROZEN_NAMING_SCOPE')
    if p.get('primitive_block_count',999)>16:
        return fail('FROZEN_NAME_SEARCH_BUDGET_EXCEEDED')
    return name_from_unit(smiles)


def _normalize_tree(n, fractions, entities, labels, anchors=False, make_labels=True):
    n=_unwrap(n); kind=n['kind']
    if kind=='source':
        m=n['molecule'];ref=m['molecule_key']
        entities[ref]={'kind':'source_molecule','graph_key':ref,'smiles':m['isomeric_smiles'],
                       'formula':m['formula'],'display_label':labels.get(ref),
                       'label_profile':NAMING,'binding_review':'not_independently_reviewed'}
        out={'kind':'source','entity_ref':ref}
    elif kind=='unit':
        u=n['unit'];p=u['periodic'];ref=p['periodic_graph_key']
        named=_bounded_unit_name(p['canonical_repeat_smiles']) if make_labels else {'status':'NEEDS_DETAILS'}
        label=None
        if named.get('status')=='PARSED':
            name=named['structure_based_name_candidate']
            label=name[5:-1] if name.startswith('poly(') and name.endswith(')') else None
        entities[ref]={'kind':'constitutional_unit','graph_key':ref,
                       'smiles':p['canonical_repeat_smiles'],'formula':p['primitive_formula'],
                       'display_label':label,'label_profile':NAMING,
                       'binding_review':'not_independently_reviewed'}
        out={'kind':'unit','entity_ref':ref}
        if anchors:
            # Preserve the declared cell and 1/2 port direction for end/count
            # binding. An unoriented periodic key alone loses this information.
            from rdkit import Chem
            out['ported_unit_basis']=Chem.MolToSmiles(Chem.MolFromSmiles(u['unit_smiles']),canonical=True,isomericSmiles=True)
    elif kind=='opaque':
        out={'kind':'unknown','literal':re.sub(r'\s+',' ',n.get('raw','').strip())}
    else:
        cs=[_normalize_tree(c,fractions,entities,labels,anchors or kind=='end_groups',make_labels)
            for c in n.get('children',[])]
        out={'kind':kind,'children':cs}
        for attr in ('operator','operators','qualifier','qualifier_dimension','class','alpha','omega',
                     'pool_semantics'):
            if attr in n:out[attr]=n[attr]
        # Preserve multiplicity; never turn an ABA sequence into a set.
        if kind=='source_pool' or (kind=='connective' and n.get('operator') in ('co','stat','ran','blend','ipn','compl')):
            out['children']=sorted(cs,key=stable_json)
        elif kind=='connective' and n.get('operator') in ('block','alt') and not anchors:
            out['children']=min((cs,list(reversed(cs))),key=stable_json)
        elif kind=='connective' and n.get('operator')=='per' and not anchors and cs:
            choices=[seq[i:]+seq[:i] for seq in (cs,list(reversed(cs))) for i in range(len(seq))]
            out['children']=min(choices,key=stable_json)
    if n.get('occurrence_id') in fractions:
        out['fractions']=sorted({stable_json(v):v for v in fractions[n['occurrence_id']]}.values(),key=stable_json)
    return out


def _assign_ids(tree):
    entries=[]
    def visit(n,path,role):
        ident='node-'+'.'.join(map(str,path))
        entries.append({'id':ident,'path':path,'kind':n['kind'],'role':role,
                        'entity_ref':n.get('entity_ref')})
        for j,c in enumerate(n.get('children',[])):
            op=n.get('operator')
            childrole=('backbone' if j==0 else 'sidechain') if op in ('graft','comb') else ('block_occurrence' if op=='block' else 'component')
            visit(c,path+[j],childrole)
    visit(tree,[0],'root')
    return entries


def _name_tree(tree,entities,directions=None,path=(0,)):
    directions=directions or {}
    here=directions.get(".".join(map(str,path)))
    if here is not None:
        return deepcopy(here["name_ast"])
    k=tree['kind'];out={'kind':k}
    if k in ('source','unit'):
        e=entities[tree['entity_ref']]
        if not e.get('display_label'): return None
        return {'kind':k,'label':e['display_label'],'entity_ref':tree['entity_ref']}
    if k in ('unknown','mixed'): return None
    if k=='end_groups' and any(n.get('kind')=='unit' for n in _leaves(tree)):
        # Canonical unoriented CU labels do not yet carry the directional
        # renumbering required to reassign alpha/omega. Refuse a whole name.
        return None
    children=[_name_tree(c,entities,directions,path+(i,)) for i,c in enumerate(tree.get('children',[]))]
    if any(c is None for c in children):return None
    out['children']=children
    for attr in ('operator','qualifier','qualifier_dimension','class','alpha','omega','pool_semantics'):
        if attr in tree:out[attr]=tree[attr]
    return out



def _build_direction_mappings(tree):
    """Chemistry runs ONCE during construction, never in frozen name replay."""
    from .end_naming import name_with_end_groups
    out={}
    def visit(n,path):
        if n['kind']=='end_groups' and len(n.get('children',[]))==1:
            child=n['children'][0]
            if child['kind']=='polymer' and len(child.get('children',[]))==1:
                u=child['children'][0]
                if u['kind']=='unit' and u.get('ported_unit_basis'):
                    r=name_with_end_groups({'unit_smiles':u['ported_unit_basis'],
                                          'end_groups':{'alpha':n['alpha'],'omega':n['omega']}})
                    if r['status']=='PARSED':
                        d=r['direction_mapping']
                        ast={'kind':'end_groups','alpha':d['alpha'],'omega':d['omega'],
                             'children':[{'kind':'polymer','children':[{'kind':'unit',
                             'label':d['unit_label'],'entity_ref':u['entity_ref']}]}]}
                        out['.'.join(map(str,path))]={'input_basis':r['input_basis'],
                              'name_ast':ast,'direction_mapping':d,'rule_refs':r['rule_refs'],
                              'profile':r['profile'],'chemical_review':'NOT_INDEPENDENTLY_REVIEWED'}
        for i,c in enumerate(n.get('children',[])):visit(c,path+(i,))
    visit(tree,(0,))
    return out


def _validate_direction_bindings(tree,mappings):
    """Pure snapshot consistency, NOT revalidation of the chemistry proof."""
    if not isinstance(mappings,dict):raise PassportError('DIRECTION_MAPPING_OBJECT_REQUIRED')
    for path,data in mappings.items():
        try:
            steps=[int(v) for v in path.split('.')]
            if not steps or steps[0]!=0 or any(i<0 for i in steps):raise ValueError()
            n=tree
            for i in steps[1:]:n=n['children'][i]
            u=n['children'][0]['children'][0]
            expected={'unit_smiles':u['ported_unit_basis'],
                      'end_groups':{'alpha':n['alpha'],'omega':n['omega']}}
            if n['kind']!='end_groups' or data['input_basis']!=expected:raise ValueError()
            ast=data['name_ast'];d=data['direction_mapping']
            if (ast['alpha']!=d['alpha'] or ast['omega']!=d['omega']
                or ast['children'][0]['children'][0]['entity_ref']!=u['entity_ref']
                or ast['children'][0]['children'][0]['label']!=d['unit_label']):raise ValueError()
            if d['repeat_count_multiplier']!=1 or d['repeat_count_offset']!=0:raise ValueError()
        except (KeyError,ValueError,TypeError,IndexError):
            raise PassportError('END_DIRECTION_BINDING_MISMATCH')

def render_name_ast(ast):
    """No chemical module calls, no mutable external state."""
    if not isinstance(ast,dict):raise PassportError('NAME_AST_REQUIRED')
    k=ast.get('kind');cs=ast.get('children',[])
    if k in ('source','unit'):return ast['label']
    if k=='polymer':return 'poly('+render_name_ast(cs[0])+')'
    if k=='group':return '('+render_name_ast(cs[0])+')'
    if k=='qualifier':return ast['qualifier']+'-'+render_name_ast(cs[0])
    if k=='end_groups':return 'alpha-'+ast['alpha']+'-omega-'+ast['omega']+'-'+render_name_ast(cs[0])
    if k=='polymer_class':return ast['class']+':'+render_name_ast(cs[0])
    if k=='source_pool':return '('+';'.join(render_name_ast(c) for c in cs)+')'
    if k in ('connective','unit_list'):
        sep='/' if k=='unit_list' else '-'+ast['operator']+'-'
        def child(c):
            text=render_name_ast(c)
            return '('+text+')' if c['kind']=='connective' and c.get('operator')!=ast.get('operator') else text
        return sep.join(child(c) for c in cs)
    raise PassportError('NAME_AST_KIND_OUT_OF_SCOPE')


def _project(core,material=False):
    tree=deepcopy(core['definition_tree'])
    def clean(n):
        n.pop('fractions',None)
        for c in n.get('children',[]):clean(c)
    if not material: clean(tree)
    # sample IDs / provenance never participate in chemical description.
    attrs={k:v for k,v in core['attributes'].items() if k!='sample_label'}
    if not material:
        attrs={k:v for k,v in attrs.items() if k not in ('number_average_molar_mass','repeat_count')}
    return {'tree':tree,'attributes':attrs,'composition_sets':core['composition_sets'] if material else [],
            'unresolved_segments':core['unresolved_segments'],'conflicts':core['conflicts'],
            'interpretation_policy':core['interpretation_policy'],
            'constitution_model':core['constitution_model']}


def _digest(passport):
    tmp=deepcopy(passport);tmp.pop('integrity',None)
    return key(passport.get('schema_version',SCHEMA)+'/snapshot',tmp)


def validate_passport(passport):
    try:
        if not isinstance(passport,dict) or passport.get('schema_version') not in (SCHEMA,SCHEMA07,SCHEMA09):
            raise PassportError('PASSPORT_SCHEMA_VERSION_UNSUPPORTED')
        required={'schema_version','policies','record','chemical_core','entities','occurrences',
                  'identity_keys','evidence','build_manifest','naming_snapshot','assessment','integrity'}
        if set(passport)!=required:raise PassportError('PASSPORT_FIELDS_MISMATCH')
        expected_naming={SCHEMA:NAMING,SCHEMA07:NAMING07,SCHEMA09:NAMING09}[passport['schema_version']]
        if passport['policies']!={'canonicalization':POLICY,'naming':expected_naming}:
            raise PassportError('PASSPORT_POLICY_VERSION_UNSUPPORTED')
        if passport['integrity'].get('snapshot_key')!=_digest(passport):
            raise PassportError('PASSPORT_INTEGRITY_MISMATCH')
        core=passport['chemical_core'];ks=passport['identity_keys']
        if ks['source_description_key']!=key(POLICY+'/source-description',_project(core)):
            raise PassportError('DESCRIPTION_KEY_MISMATCH')
        if ks['description_key']!=key(POLICY+'/description',_project(core,True)):
            raise PassportError('REPORTED_MATERIAL_KEY_MISMATCH')
        directions=passport['naming_snapshot'].get('end_direction_mappings',{})
        _validate_direction_bindings(core['definition_tree'],directions)
        expected=_name_tree(core['definition_tree'],passport['entities'],directions)
        if passport['naming_snapshot']['source_or_cu_ast']!=expected:
            raise PassportError('NAME_AST_CORE_MISMATCH')
        if passport['occurrences']!=_assign_ids(core['definition_tree']):
            raise PassportError('OCCURRENCE_INDEX_MISMATCH')
        if ks['material_identity_key'] is not None:
            raise PassportError('MATERIAL_IDENTITY_NOT_IMPLEMENTED')
        return {'status':'PARSED','scope':'snapshot_and_projected_keys','signature_verified':False,
                'chemical_truth_verified':False}
    except (KeyError,TypeError,ValueError,RecursionError) as e:
        return fail(str(e),'INVALID')


def _create(kernel,inputs):
    allowed={'name','composition','compositions','attributes','interpretation_policy','source_ref',
             'raw_text','evidence_assertions','unresolved_segments','conflicts','record_id',
              'previous_passport','formation','naming_profile','supplied_constitution'}
    if set(inputs)-allowed:raise PassportError('UNKNOWN_PASSPORT_INPUT_FIELD:'+','.join(sorted(set(inputs)-allowed)))
    profile=inputs.get('naming_profile',NAMING)
    if profile not in (NAMING,NAMING07):raise PassportError('NAMING_PROFILE_UNSUPPORTED')
    name=inputs.get('name')
    if not isinstance(name,str) or not name.strip():raise PassportError('POLYMER_NAME_REQUIRED')
    attrs_input=inputs.get('attributes',{})
    if not isinstance(attrs_input,dict) or set(attrs_input)-ATTRS:
        raise PassportError('ATTRIBUTE_OUT_OF_SCOPE')
    attrs={attr:_normalize_attr(attr,attrs_input[attr]) if attr in attrs_input else field()
           for attr in sorted(ATTRS)}
    policy=inputs.get('interpretation_policy','evidence_only')
    parse_input={'name':name,'interpretation_policy':policy}
    if inputs.get('formation'):parse_input['formation']=inputs['formation']
    parsed=kernel.parse(parse_input)
    if not parsed.get('ast'):
        return {**fail(parsed.get('reason_code','NO_AST'),parsed['status']),'raw_name':name}
    # Bare molecular names do not become polymer passports.
    def wrapped(n):
        return n.get('kind') in ('polymer','polymer_class') or any(wrapped(c) for c in n.get('children',[]))
    if not wrapped(parsed['ast']):
        # This is a scope/grammar boundary, not evidence the chemical name is
        # invalid. A bare molecular graph does not define polymer connectivity.
        return {**fail('POLYMER_WRAPPER_OR_DESCRIPTION_REQUIRED',
                       'NEEDS_DETAILS' if parsed['status']=='PARSED' else 'UNSUPPORTED'),
                'raw_name':name,'legacy_parse_status':parsed['status']}
    issues=deepcopy(inputs.get('conflicts',[]))
    if not isinstance(issues,list) or len(issues)>128 or any(not isinstance(x,dict) or x.get('severity') not in ('partial','conflicting') for x in issues):
        raise PassportError('TYPED_CONFLICT_ARRAY_REQUIRED')
    for attr,f in attrs.items():
        if f['knowledge_status'] in ('ambiguous','conflicting'):
            issues.append({'code':'ATTRIBUTE_'+f['knowledge_status'].upper(),'field':attr,
                           'severity':'conflicting' if f['knowledge_status']=='conflicting' else 'partial'})
    segments=inputs.get('unresolved_segments',[])
    if not isinstance(segments,list) or len(segments)>128 or any(not isinstance(x,str) for x in segments):
        raise PassportError('UNRESOLVED_TEXT_ARRAY_REQUIRED')
    if inputs.get('record_id') is not None and (not isinstance(inputs['record_id'],str) or not 0<len(inputs['record_id'])<=1000):
        raise PassportError('RECORD_ID_REQUIRED_AS_TEXT')
    fractions,sets=_bind_compositions(parsed,inputs,kernel.registry,issues)
    labels,snapshot=_display_labels(kernel.registry)
    display_key=None
    if profile==NAMING07:
        generated,display_key=_generated_labels_v07()
        labels={**generated,**labels}  # established display labels keep priority
    entities={}
    anchored=(attrs['end_groups']['knowledge_status']=='specified' or attrs['repeat_count']['knowledge_status']=='specified')
    tree=_normalize_tree(parsed['ast'],fractions,entities,labels,anchored,parsed['status']=='PARSED')
    # Promote explicitly supplied end groups / tacticity into the display tree
    # only if not already represented. Never silently replace a conflicting one.
    def collect(n,kind):return ([n] if n['kind']==kind else [])+sum([collect(c,kind) for c in n.get('children',[])],[])
    for attr,kind in [('end_groups','end_groups'),('tacticity','qualifier')]:
        f=attrs[attr]
        if f['knowledge_status']!='specified': continue
        nodes=collect(tree,kind)
        if attr=='tacticity':nodes=[n for n in nodes if n.get('qualifier_dimension')=='stereodescription']
        if nodes:
            ok=(len(nodes)==1 and ({'alpha':nodes[0]['alpha'],'omega':nodes[0]['omega']}==f['value']
                if attr=='end_groups' else nodes[0]['qualifier']==f['value']))
            if not ok:issues.append({'code':'ATTRIBUTE_NAME_CONFLICT','severity':'conflicting','field':attr})
        elif attr=='end_groups':tree={'kind':'end_groups',**f['value'],'children':[tree]}
        else:tree={'kind':'qualifier','qualifier':f['value'],'qualifier_dimension':'stereodescription','children':[tree]}
    # Names with these qualifiers and the equivalent explicit-attribute request
    # produce the same complete described tree and field values.
    def infer_root(n):
        while n.get('kind')=='group':n=n['children'][0]
        if n.get('kind')=='end_groups':
            attrs['end_groups']=field({'alpha':n['alpha'],'omega':n['omega']})
            infer_root(n['children'][0])
        elif n.get('kind')=='qualifier' and n.get('qualifier_dimension')=='stereodescription' and n.get('qualifier') in ('isotactic','syndiotactic','atactic'):
            attrs['tacticity']=field(n['qualifier']);infer_root(n['children'][0])
    infer_root(tree)
    period=None;repeat=None;support=None;exclusions=[]
    if parsed.get('product_compilation',{}).get('periodic',{}).get('status')=='PARSED':
        p=parsed['product_compilation']['periodic'];repeat=p['canonical_repeat_smiles'];support='explicit_formation_assumption'
    elif parsed.get('idealized_constitution',{}).get('status')=='PARSED':
        model=parsed['idealized_constitution'];p=model['periodic'];repeat=p['canonical_repeat_smiles']
        support='naming_convention_model';exclusions=model['excluded_fields']
    elif parsed.get('semantic_projection',{}).get('constitution_key'):
        units=[c for c in parsed['components'] if c['kind']=='unit']
        if len(units)==1:
            p=units[0]['unit']['periodic'];repeat=p['canonical_repeat_smiles'];support='structure_name_candidate'
    supplied=None
    if inputs.get('supplied_constitution') is not None:
        from .supplied_constitution import validate as validate_supplied
        supplied=validate_supplied(inputs['supplied_constitution'])
        supplied_period=supplied['periodic']
        if supplied_period.get('status')=='PARSED':
            if repeat and p['periodic_graph_key']!=supplied_period['periodic_graph_key']:
                issues.append({'code':'SUPPLIED_GRAPH_NAME_CONSTITUTION_CONFLICT','severity':'conflicting'})
            p=supplied_period;repeat=p['canonical_repeat_smiles'];support='explicit_supplied_candidate_graph'
        else:
            issues.append({'code':'SUPPLIED_CONSTITUTION_OUTSIDE_PERIODIC_SCOPE','severity':'partial',
                           'reason_code':supplied_period.get('reason_code')})
    if repeat:
        period={'graph_key':p['periodic_graph_key'],'canonical_repeat_smiles':repeat,
                'scope':p['scope'],'support_type':support,
                'excluded_fields':sorted(set(exclusions+['end_groups','sample_identity','periodic_stereo'])),
                'actual_product_verified':False}
    named=_bounded_unit_name(repeat) if repeat else None
    structure_ast=None
    if named and named['status']=='PARSED':
        text=named['structure_based_name_candidate']
        structure_ast={'kind':'polymer','children':[{'kind':'unit','label':text[5:-1],
                        'entity_ref':period['graph_key']}]}
    unresolved=sorted(set(str(s).strip() for s in inputs.get('unresolved_segments',[]) if str(s).strip()))
    conflicts=sorted({stable_json(x):x for x in issues}.values(),key=stable_json)
    core={'definition_tree':tree,'attributes':attrs,'composition_sets':sets,
          'constitution_model':period,'interpretation_policy':policy,
          'unresolved_segments':unresolved,'conflicts':conflicts}
    raw=inputs.get('raw_text',name)
    if not isinstance(raw,str) or len(raw)>20000:raise PassportError('RAW_TEXT_LIMIT')
    source=inputs.get('source_ref','interactive-input')
    if not isinstance(source,str) or len(source)>1000:raise PassportError('SOURCE_REF_INVALID')
    assertions=deepcopy(inputs.get('evidence_assertions',[]))
    if supplied:
        assertions.append({'kind':'SUPPLIED_CONSTITUTION_CANDIDATE','details':supplied,
                           'source_fact':False,'independent_review':'NOT_REVIEWED'})
    if not isinstance(assertions,list) or len(assertions)>256:raise PassportError('ASSERTION_ARRAY_LIMIT')
    for a in assertions:
        if not isinstance(a,dict):raise PassportError('ASSERTION_OBJECT_REQUIRED')
        span=a.get('span')
        if span is not None:
            if (not isinstance(span,list) or len(span)!=2 or any(type(v)!=int for v in span)
                or not 0<=span[0]<=span[1]<=len(raw) or a.get('quote')!=raw[span[0]:span[1]]):
                raise PassportError('EVIDENCE_SPAN_OR_QUOTE_MISMATCH')
    assertions=sorted({stable_json(a):a for a in assertions}.values(),key=stable_json)
    evidence={'source_ref':source,'raw_text':raw,'assertions':assertions,
              'input_key':key('evidence-input/0.6',[source,raw]),
              'independent_source_count':1,
              'original_name':name,'legacy_descriptor_key':parsed.get('semantic_projection',{}).get('descriptor_key')}
    status='CONFLICT' if any(x.get('severity')=='conflicting' for x in conflicts) else (
        'PARTIAL' if parsed['status']!='PARSED' or unresolved or conflicts else 'PARSED')
    directions=_build_direction_mappings(tree) if profile==NAMING07 else {}
    root_direction=directions.get('0')
    if root_direction and period:
        structure_ast=deepcopy(root_direction['name_ast'])
    build_manifest={'kernel':'identity/0.8','contract_engine':'identity/0.7' if profile==NAMING07 else 'identity/0.6',
                    'name_parser':parsed.get('engine_version'),
                    'registry_snapshot_key':snapshot,'naming_profile':profile,
                    'chemical_rule_review':'NOT_INDEPENDENTLY_COMPLETED'}
    if supplied:
        build_manifest['supplied_constitution_contract']=supplied['contract']
    levers=kernel.registry.lever_state()
    if not levers['default_namespace_unchanged']:
        # Opt-in parse levers change how a name resolves, so the card names the
        # tables it was built with; the default run stays byte-identical.
        build_manifest['parse_levers']=levers
    card={'schema_version':SCHEMA07 if profile==NAMING07 else SCHEMA,'policies':{'canonicalization':POLICY,'naming':profile},
          'record':{'record_id':inputs.get('record_id') or key('evidence-record/0.6',[source,raw]),
                    'revision':1,'parent_snapshot_key':None},
          'chemical_core':core,'entities':dict(sorted(entities.items())),
          'occurrences':_assign_ids(tree),
          'identity_keys':{
              'source_description_key':key(POLICY+'/source-description',_project(core)),
              'description_key':key(POLICY+'/description',_project(core,True)),
              'constitution_key':period['graph_key'] if period else None,
              'material_identity_key':None,'evidence_key':key('evidence/0.6',evidence)},
          'evidence':evidence,
          'build_manifest':build_manifest,
          'naming_snapshot':{'profile':profile,'source_or_cu_ast':_name_tree(tree,entities,directions),
                             'structure_ast':structure_ast,
                             'structure_support_scope':period['scope'] if period else None,
                             'preferred_iupac_name':None,'full_iupac_conformance':False,
                             'graph_roundtrip_consistent':named.get('graph_roundtrip_consistent') if named else None},
          'assessment':{'status':status,'parsing_status':parsed['status'],
                        'exact_material_identity':False,'independently_reviewed':False,
                        'unresolved_leaf_count':sum(n['kind']=='unknown' for n in _leaves(tree)),
                        'full_scope_ready':False}}
    if profile==NAMING07:
        for entity in card['entities'].values():entity['label_profile']=profile
        card['build_manifest']['generated_display_lexicon_key']=display_key
        card['naming_snapshot']['end_direction_mappings']=directions
        card['naming_snapshot']['structure_includes_end_groups']=bool(root_direction and period)
    previous=inputs.get('previous_passport')
    if previous is not None:
        if validate_passport(previous)['status']!='PARSED':raise PassportError('PREVIOUS_PASSPORT_INVALID')
        if inputs.get('record_id') and inputs['record_id']!=previous['record']['record_id']:
            raise PassportError('REVISION_RECORD_ID_CONFLICT')
        card['record']={'record_id':previous['record']['record_id'],
                        'revision':previous['record']['revision']+1,
                        'parent_snapshot_key':previous['integrity']['snapshot_key']}
    card['integrity']={'snapshot_key':_digest(card),'is_signature':False}
    return {'status':status,'passport':card,'exact_material_identity':False}


def create_passport(kernel,inputs):
    try:
        if inputs.get('naming_profile')==NAMING09:
            from .naming_upgrade import upgrade_passport_naming
            base=_create(kernel,{**inputs,'naming_profile':NAMING07})
            return upgrade_passport_naming(base['passport'],increment_revision=False) if base.get('passport') else base
        return _create(kernel,inputs)
    except (ValueError,KeyError,TypeError,RecursionError) as e:return fail(str(e),'INVALID')


def name_from_passport(passport,mode='source'):
    v=validate_passport(passport)
    if v['status']!='PARSED':return v
    if mode not in ('source','structure'):return fail('NAME_MODE_OUT_OF_SCOPE','INVALID')
    core=passport['chemical_core'];snap=passport['naming_snapshot'];ast=snap['source_or_cu_ast' if mode=='source' else 'structure_ast']
    omissions=[]
    if core['composition_sets']:omissions.append('composition_with_basis_and_values')
    for attr in ('repeat_count','number_average_molar_mass','sample_label'):
        if core['attributes'][attr]['knowledge_status']=='specified':omissions.append(attr)
    if mode=='structure':
        omissions += ['architecture_outside_periodic_backbone','tacticity','sample_identity']
        if not snap.get('structure_includes_end_groups'):omissions.append('end_groups')
    if passport['assessment']['status']=='CONFLICT':
        return fail('CONFLICTING_DESCRIPTION_NOT_NAMED','CONFLICT',preferred_iupac_name=None)
    if passport['assessment']['status']!='PARSED':
        return fail('UNRESOLVED_DESCRIPTION_NOT_NAMED_AS_WHOLE','PARTIAL',
                    supported_projection_candidate=render_name_ast(ast) if ast else None,
                    preferred_iupac_name=None)
    if ast is None:
        return fail('FROZEN_NAMING_LABEL_STRUCTURE_OR_END_DIRECTION_UNAVAILABLE','NEEDS_DETAILS',
                    preferred_iupac_name=None)
    return {'status':'PARSED','name_candidate':render_name_ast(ast),'name_ast':deepcopy(ast),
            'profile':snap['profile'],'mode':mode,
            'scope':('source_or_cu_description' if mode=='source' else ('end_capped_regular_single_chain_candidate' if snap.get('structure_includes_end_groups') else snap['structure_support_scope'])),
            'omitted_fields':sorted(set(omissions)),'preferred_iupac_name':None,
            'full_iupac_conformance':False,'registry_or_model_calls':0,
            'same_snapshot_same_name':True,'exact_material_identity':False}


def compare_passports(left,right):
    for p in (left,right):
        v=validate_passport(p)
        if v['status']!='PARSED':return v
    a=left['identity_keys'];b=right['identity_keys']
    complete=all(p['assessment']['status']=='PARSED' for p in (left,right))
    same=a['description_key']==b['description_key']
    return {'status':'PARSED','relation':('SAME_DESCRIPTION_CANDIDATE' if complete else 'SAME_PARTIAL_DESCRIPTION') if same else 'DIFFERENT_DESCRIPTIONS_OR_REFINEMENT',
            'same_description':same,
            'same_source_description':a['source_description_key']==b['source_description_key'],
            'same_constitution_at_scope':a['constitution_key']==b['constitution_key'] if a['constitution_key'] and b['constitution_key'] else None,
            'exact_material_identity':False,
            'source_names': [name_from_passport(p) for p in (left,right)]}

"""Lossless polymer-name syntax with typed operators and occurrence instances.
Pure syntax/constraint processing. No graph key is fabricated for an opaque leaf.
"""
from __future__ import annotations
import re
from .common import key,stable_json,fail
from .registry import normalize_alias
from .queue_rules import name_diagnostic
from .units import resolve_unit,TOKENS
PAIRS={'(':')','[':']','{':'}'}
OPS={'co','stat','ran','alt','per','block','graft','blend','comb','ipn','sipn','compl','net'}
TOPOLOGY={'star','branch','cyclo','net','comb','brush','dendri'}
PREFIXES=TOPOLOGY|{'isotactic','syndiotactic','atactic','cis','trans','i','s','a'}
MAX_LEN=5000;MAX_DEPTH=48

def bracket_check(s):
    stack=[];errors=[];depth=0
    for i,c in enumerate(s):
        if c in PAIRS:stack.append((c,i));depth=max(depth,len(stack))
        elif c in PAIRS.values():
            if not stack:errors.append({'code':'EXTRA_CLOSE','position':i})
            else:
                a,j=stack.pop()
                if PAIRS[a]!=c:errors.append({'code':'BRACKET_MISMATCH','position':i,'opening':j,'expected':PAIRS[a]})
    errors.extend({'code':'MISSING_CLOSE','position':i,'expected':PAIRS[c]} for c,i in stack)
    return {'valid':not errors,'max_depth':depth,'errors':errors}

def encloses(s):
    if len(s)<2 or s[0] not in PAIRS or s[-1]!=PAIRS[s[0]]:return False
    depth=0
    for i,c in enumerate(s):
        if c in PAIRS:depth+=1
        elif c in PAIRS.values():depth-=1
        if depth==0 and i<len(s)-1:return False
    return depth==0

def split_top(s,slash=False):
    depth=0;last=0;out=[];ops=[];i=0
    while i<len(s):
        c=s[i]
        if c in PAIRS:depth+=1
        elif c in PAIRS.values():depth-=1
        elif depth==0:
            m=re.match(r'-\s*('+('|'.join(sorted(OPS,key=len,reverse=True)))+r')\s*-',s[i:]) if c=='-' else None
            if slash and c=='/':m=True
            if m:
                width=1 if m is True else len(m[0]);op='/' if m is True else m[1]
                out.append((s[last:i],last));ops.append(op);i+=width;last=i;continue
        i+=1
    if ops:out.append((s[last:],last))
    return out,ops


def split_pool(s):
    """Split semicolon source alternatives only at the current bracket depth."""
    depth=0;last=0;parts=[]
    for i,c in enumerate(s):
        if c in PAIRS:depth+=1
        elif c in PAIRS.values():depth-=1
        elif c==';' and depth==0:
            parts.append((s[last:i],last));last=i+1
    if parts:parts.append((s[last:],last))
    return parts

from .finite_chains import resolve_end_group

class Parser:
    def __init__(self,registry):self.registry=registry
    def _resolve_unit(self, name):
        result = resolve_unit(name)
        hook = getattr(self.registry, "resolve_unit", None)
        return hook(name, result) if hook and result.get("status") != "PARSED" else result

    def parse(self,name,**context):
        base={'raw_name':name,'engine_version':'syntax/0.5.1-source-pool-precedence','exact_material_identity':False,'preferred_iupac_name':None,'exact_catalog_record_id':None}
        if not isinstance(name,str):return fail('NAME_MUST_BE_TEXT','INVALID',**base)
        if not name.strip():return fail('EMPTY_INPUT','INVALID',**base)
        if len(name)>MAX_LEN:return fail('NAME_LENGTH_LIMIT','UNSUPPORTED',**base)
        b=bracket_check(name)
        if not b['valid']:return fail('BRACKET_ERROR','INVALID',brackets=b,**base)
        if b['max_depth']>MAX_DEPTH:return fail('NAME_DEPTH_LIMIT','UNSUPPORTED',brackets=b,**base)
        issues=[];count=0
        def rec(raw,start=0,depth=0,role='source_or_unit'):
            nonlocal count
            shift=len(raw)-len(raw.lstrip());s=raw.strip();start+=shift;count+=1
            common={'raw':s,'span':[start,start+len(s)]}
            if count>512 or depth>MAX_DEPTH:issues.append('TREE_LIMIT');return {**common,'kind':'opaque','reason':'TREE_LIMIT'}
            if not s:issues.append('EMPTY_COMPONENT');return {**common,'kind':'opaque','reason':'EMPTY_COMPONENT'}
            end=re.match(r'^(?:α|alpha)-(.+?)-(?:ω|omega)-(.+?)(-?)(poly.+)$',s)
            if end:
                alpha_resolution=resolve_end_group(end[1]);omega_resolution=resolve_end_group(end[2])
                if alpha_resolution['status']!='PARSED' or omega_resolution['status']!='PARSED':issues.append('UNRESOLVED_END_GROUP')
                return {**common,'kind':'end_groups','alpha':end[1],'omega':end[2],'alpha_resolution':alpha_resolution,'omega_resolution':omega_resolution,'orientation_anchored':True,'delimiter_form':'standard_hyphen' if end[3] else 'catalog_adjacent_poly', 'children':[rec(end[4],start+s.index(end[4]),depth+1,role)]}
            parts,ops=split_top(s)
            if ops:
                kind='connective' if len(set(ops))==1 else 'mixed'
                if kind=='mixed':issues.append('MIXED_CONNECTIVES_REQUIRE_GROUPING')
                return {**common,'kind':kind,'operator':ops[0] if kind=='connective' else None,'operators':ops,'children':[rec(t,start+p,depth+1,role) for t,p in parts]}
            if encloses(s):return {**common,'kind':'group','children':[rec(s[1:-1],start+1,depth+1,role)]}
            pre=re.match(r'([a-z]+)-',s)
            if pre and pre[1] in PREFIXES:
                return {**common,'kind':'qualifier','qualifier':pre[1],'qualifier_dimension':'topology' if pre[1] in TOPOLOGY else 'stereodescription','children':[rec(s[len(pre[0]):],start+len(pre[0]),depth+1,role)]}
            cl=re.match(r'^(polyether|polyalkylene|polyester|polyamide):\s*(.+)$',s)
            if cl:return {**common,'kind':'polymer_class','class':cl[1],'children':[rec(cl[2],start+s.index(cl[2]),depth+1,'source')]}
            # Group lists bind outside a poly wrapper; never consume a leading
            # polymer as the entire semicolon-delimited source collection.
            pools=split_pool(s)
            if pools:
                return {**common,'kind':'source_pool','sequence':'not_specified','pool_semantics':'catalog_source_alternatives_candidate','children':[rec(t,start+p,depth+1,'source') for t,p in pools]}
            if s.startswith('poly'):
                body=s[4:].lstrip();off=start+len(s)-len(body)
                if not body:issues.append('EMPTY_POLY_BODY');return {**common,'kind':'opaque','reason':'EMPTY_POLY_BODY'}
                if body[0] in PAIRS:
                    if not encloses(body):issues.append('UNCONSUMED_TAIL');return {**common,'kind':'opaque','reason':'UNCONSUMED_TAIL'}
                    return {**common,'kind':'polymer','children':[rec(body[1:-1],off+1,depth+1,'source_or_unit')]}
                return {**common,'kind':'polymer','children':[rec(body,off,depth+1,'source_or_unit')]}
            parts,slash=split_top(s,True)
            if slash:
                return {**common,'kind':'unit_list','operator':'/','sequence':'unspecified','children':[rec(t,start+p,depth+1,'unit') for t,p in parts]}
            # Explicit diyl/subunit notation is not an actual-monomer list.
            unmistakable=bool(re.search(r'diyl|ylene|silan|silox|^oxy|^imino|^carbonyl|^thio|^sulfonyl',s)) and s not in ('ethylene','propylene')
            u=self._resolve_unit(s) if role=='unit' or unmistakable else None
            if u and u['status']=='PARSED':return {**common,'kind':'unit','role':'constitutional_unit','unit':u}
            if role!='unit':
                m=self.registry.resolve(s)
                if m['status']=='PARSED':return {**common,'kind':'source','role':'real_or_assumed_naming_source','molecule':m}
                if m['status']=='AMBIGUOUS':issues.append('AMBIGUOUS_NAME_BINDING')
            u=u or self._resolve_unit(s)
            if u['status']=='PARSED':return {**common,'kind':'unit','role':'constitutional_unit','unit':u}
            issues.append('UNRESOLVED_LEAF');return {**common,'kind':'opaque','role':role,'reason':'UNRESOLVED_LEAF','diagnostic':name_diagnostic(s)}
        ast=rec(name);leaves=[];operators=[]
        def walk(n,path):
            n['occurrence_id']='occ-'+'.'.join(map(str,path))
            if n.get('operator'):operators.append({'operator':n['operator'],'occurrence_id':n['occurrence_id']})
            if not n.get('children'):leaves.append(n)
            for i,c in enumerate(n.get('children',[])):walk(c,path+[i])
        walk(ast,[0]);unknown=[x for x in leaves if x['kind']=='opaque'];invalid=any(x in issues for x in ['EMPTY_COMPONENT','EMPTY_POLY_BODY'])
        projection=describe(ast)
        if not unknown and not any(x in issues for x in ['MIXED_CONNECTIVES_REQUIRE_GROUPING','TREE_LIMIT','UNRESOLVED_END_GROUP']):status='PARSED'
        else:status='INVALID' if invalid else 'PARTIAL'
        unit_leaves=[x for x in leaves if x['kind']=='unit']
        # Constitution only exists for one explicit CU, without mixing it into source keys.
        constitution=None
        def has_topology(n):return n.get('qualifier_dimension')=='topology' or any(has_topology(c) for c in n.get('children',[]))
        if len(unit_leaves)==1 and len(leaves)==1 and not operators and not has_topology(ast):constitution=unit_leaves[0]['unit']['periodic']['periodic_graph_key']
        seqs=[o['operator'] for o in operators if o['operator'] in {'co','stat','ran','alt','per'}]
        archs=[o['operator'] for o in operators if o['operator'] in {'block','graft','comb','blend','ipn','sipn','compl','net'}]
        semantic={'descriptor':projection,'descriptor_key':key('descriptor/0.2',projection) if status=='PARSED' else None,
                  'constitution_key':constitution,'sequence_kind':{'co':'unspecified','stat':'statistical','ran':'random','alt':'alternating','per':'periodic'}.get(seqs[0]) if len(set(seqs))==1 else ('nested' if seqs else 'not_specified'),
                  'architecture_kind':archs[0] if len(set(archs))==1 else ('nested' if archs else 'not_specified'),
                  'constitution_scope':'periodic_backbone_projection_excluding_end_groups' if constitution else None,'component_occurrences':len(leaves),'composition':context.get('composition'),'declared_type':context.get('declared_type')}
        return {**base,'status':status,'reason_code':None if status=='PARSED' else ('INVALID_COMPONENT' if invalid else 'CHEMISTRY_OR_GROUPING_PARTIAL'),
                'syntax_status':'PARTIAL' if any(x in issues for x in ['UNCONSUMED_TAIL','TREE_LIMIT','MIXED_CONNECTIVES_REQUIRE_GROUPING']) else 'PARSED',
                'ast':ast,'name_ast':{'operator':operators[0]['operator'] if operators else None,'leaf_count':len(leaves),'tree':ast},'components':leaves,'operators':operators,'issues':sorted(set(issues)),
                'semantic_projection':semantic,'resolved_leaves':len(leaves)-len(unknown),'total_leaves':len(leaves),
                'name_bindings_independently_reviewed':all(x.get('molecule',{}).get('binding_status')=='REVIEWED' for x in leaves) if leaves else False,
                'material_missing_fields':['unit_connectivity_if_source_only','stereo','end_groups','composition_if_applicable','sample_fields']}

def describe(n,anchored=False):
    kind=n['kind'];cs=n.get('children',[])
    if kind=='source':return {'kind':'source','molecule_key':n['molecule']['molecule_key']}
    if kind=='unit':return {'kind':'unit','periodic_graph_key':n['unit']['periodic']['periodic_graph_key']}
    if kind=='opaque':return {'kind':'unknown','literal':normalize_alias(n['raw'])}
    if kind=='group':return describe(cs[0],anchored)
    if kind=='source_pool':return {'kind':'source_pool','sequence':'not_specified','children':sorted([describe(c,anchored) for c in cs],key=stable_json)}
    if kind=='end_groups':return {'kind':kind,'alpha':n['alpha'],'omega':n['omega'],'child':describe(cs[0],True)}
    children=[describe(c,anchored) for c in cs]
    if kind=='connective':
        op=n['operator']
        if op in ('co','stat','ran','blend','ipn','compl'):children=sorted(children,key=stable_json)
        if op=='block' and not anchored:children=min([children,list(reversed(children))],key=stable_json)
        if op=='per' and not anchored:
            candidates=[seq[i:]+seq[:i] for seq in [children,list(reversed(children))] for i in range(len(seq))];children=min(candidates,key=stable_json)
        # Graft/comb and semi-IPN component roles are not sorted or reversed.
        return {'kind':kind,'operator':op,'children':children}
    out={'kind':kind,'children':children}
    for k in ['qualifier','qualifier_dimension','alpha','omega','class','operator','sequence','operators']:
        if k in n:out[k]=n[k]
    return out

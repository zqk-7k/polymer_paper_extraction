"""Graph-to-name candidates for a finite, declared CU lexicon.

The graph canonicalizer chooses no IUPAC preferred name. This module enumerates
orientations and subunit decompositions, gives a candidate + decision trace,
and checks graph preservation with the independently separated CU parser. That
round-trip is a regression check, NOT independent IUPAC certification.
"""
from functools import lru_cache
from .common import fail,key,stable_json
from .units import TOKENS,resolve_unit
from .periodic import split_blocks,reverse_unit,canonicalize_unit

PROFILE='iupac-candidate-subprofile/0.2'
# These names are subunit primitives, not a table of whole-polymer answers.
# Lower-priority synonyms are excluded from deterministic display selection.
EXCLUDED={'thio','1-vinylethane-1,2-diyl','ethane-1,2-diyl','vinylene'}

def render_ast(ast):
    """Pure serializable NameAST renderer. No global/current input state."""
    k=ast['kind'];cs=ast.get('children',[])
    if k in ('source','unit','opaque'):return ast['raw']
    if k=='source_pool':return ';'.join(render_ast(c) for c in cs)
    if k=='group':return '('+render_ast(cs[0])+')'
    if k=='polymer':return 'poly('+render_ast(cs[0])+')'
    if k=='qualifier':return ast['qualifier']+'-'+render_ast(cs[0])
    if k=='end_groups':return 'alpha-'+ast['alpha']+'-omega-'+ast['omega']+'-'+render_ast(cs[0])
    if k=='polymer_class':return ast['class']+':'+render_ast(cs[0])
    if k in ('connective','unit_list'):
        sep='/' if k=='unit_list' else '-'+ast['operator']+'-'
        def child(c):
            v=render_ast(c)
            return '('+v+')' if c['kind']=='connective' and c.get('operator')!=ast.get('operator') else v
        return sep.join(child(c) for c in cs)
    return ast['raw']

def source_name(parsed):
    if parsed['status']!='PARSED':return fail('ALL_NAME_FRAGMENTS_MUST_BE_RESOLVED','PARTIAL')
    ast=parsed['ast']
    return {'status':'PARSED','name_ast':ast,'name_candidate':render_ast(ast),
            'name_kind':'BOUNDED_SOURCE_OR_CU_RENDERING','profile':PROFILE,
            'preferred_iupac_name':None,'full_iupac_conformance':False,
            'rule_trace':['NAME-AST-LOSSLESS-NESTING','OCCURRENCE-ROLE-PRESERVATION'],
            'independent_rule_validation':'NOT_COMPLETED'}

@lru_cache(maxsize=1)
def lexicon():
    entries=[]
    for name,smi in TOKENS.items():
        if name in EXCLUDED:continue
        try:b=split_blocks(smi)
        except ValueError:continue
        # Bounded ordering preference, not the general RSSOP seniority engine.
        priority={'oxy':0,'sulfanediyl':1,'sulfonyl':1,'imino':2,'dimethylsilanediyl':3,'silanediyl':3}.get(name,5)
        if 'phenylene' in name:priority=4
        entries.append((tuple(b),name,priority))
        rev=tuple(reverse_unit(x) for x in reversed(b))
        if rev!=tuple(b):entries.append((rev,name,priority))
    return entries

def emit_subunit_name(names):
    # Enclose nontrivial locanted subunits when concatenating.
    if len(names)==1:return names[0]
    return ''.join(('('+x+')') if x[0].isdigit() or x=='dimethylsilanediyl' else x for x in names)

@lru_cache(maxsize=10000)
def name_from_unit(smiles):
    p=canonicalize_unit(smiles)
    if p['status']!='PARSED':return fail('PERIODIC_GRAPH_OUTSIDE_NAMING_PROFILE',periodic=p)
    word=p['primitive_blocks'];n=len(word)
    if n>80:return fail('NAMING_SEARCH_LIMIT',periodic=p)
    candidates=[]
    rev=[reverse_unit(x) for x in reversed(word)]
    for direction,seq in [('forward',word),('reverse',rev)]:
        for shift in range(n):
            seq=seq if shift==0 else (word if direction=='forward' else rev)
            ordered=seq[shift:]+seq[:shift]
            paths={0:[([],[])]}
            for i in range(n):
                for names,pri in paths.get(i,[]):
                    for block,label,priority in lexicon():
                        j=i+len(block)
                        if tuple(ordered[i:j])==block:
                            paths.setdefault(j,[]).append((names+[label],pri+[priority]))
                # Bounded alternatives; no successful label is accepted without
                # full graph round-trip below.
                for j in list(paths):
                    if len(paths[j])>128:paths[j]=sorted(paths[j],key=lambda z:(len(z[0]),z[1],z[0]))[:128]
            for names,pri in paths.get(n,[]):
                text='poly('+emit_subunit_name(names)+')'
                u=resolve_unit(emit_subunit_name(names))
                if u['status']=='PARSED' and u['periodic']['periodic_graph_key']==p['periodic_graph_key']:
                    rank=(pri[0],len(names),tuple(pri),text)
                    candidates.append((rank,{'name':text,'subunits':names,'direction':direction,
                                             'rotation_blocks':shift,
                                             'oriented_primitive_blocks':list(ordered),
                                             'subunit_block_lengths':[len(split_blocks(resolve_unit(x)['unit_smiles'])) for x in names]}))
    if not candidates:return fail('NO_COMPLETE_SUBUNIT_DECOMPOSITION',periodic=p,profile=PROFILE)
    candidates.sort(key=lambda x:x[0]);chosen_rank,chosen=candidates[0]
    unique=list(dict.fromkeys(x[1]['name'] for x in candidates))
    # Keep the bounded candidate selector auditable.  These fields describe
    # the deterministic search only; they are not a preferred-IUPAC claim.
    # These are parser block positions, not IUPAC locants.  Lengths are taken
    # from the selected decomposition so a multi-block subunit is replayable.
    positions=[];cursor=1
    for label,length in zip(chosen['subunits'],chosen['subunit_block_lengths']):
        positions.append({'subunit':label,'block_start':cursor,'block_length':length})
        cursor+=length
    tied=[x[1] for x in candidates if x[0]==chosen_rank]
    selection_trace={
        'seniority': {'lexicon_priority': list(chosen_rank[2]),
                      'primary_priority': chosen_rank[0],
                      'rule_scope':'bounded_project_lexicon'},
        'path': {'direction':chosen['direction'],
                 'rotation_blocks':chosen['rotation_blocks'],
                 'oriented_primitive_blocks':chosen['oriented_primitive_blocks']},
        'locant': {'basis':'parser_oriented_primitive_block_positions_not_chemical_locants',
                   'assignments':positions},
        'tie_break': {'ordered_keys':['lexicon_priority','subunit_count',
                                      'priority_vector','rendered_candidate'],
                      'selected_rank':list(chosen_rank[:2])+[list(chosen_rank[2]),chosen_rank[3]],
                      'candidate_paths_considered':len(candidates),
                      # Backward-compatible field name; this counts paths,
                      # not deduplicated rendered names or reviewed answers.
                      'alternatives_considered':len(candidates),
                      'equal_best_paths':[{'direction':x['direction'],'rotation_blocks':x['rotation_blocks']}
                                          for x in tied]},
        'candidate_only':True,
        'preferred_iupac_name':None,
    }
    return {'status':'PARSED','structure_based_name_candidate':chosen['name'],'preferred_iupac_name':None,
            'profile':PROFILE,'full_iupac_conformance':False,'graph_roundtrip_consistent':True,
            'independent_rule_validation':'NOT_COMPLETED','periodic':p,
            'rule_trace':[{'rule':'NAME-CU-DECOMPOSE','subunits':chosen['subunits']},
                          {'rule':'NAME-BOUNDED-ORIENTATION','direction':chosen['direction'],'rotation_blocks':chosen['rotation_blocks']},
                          {'rule':'NAME-GRAPH-PRESERVATION','periodic_graph_key':p['periodic_graph_key']}],
            'selection_trace':selection_trace,
            'alternative_graph_preserving_names':unique[:12],
            'limitation':'Candidate lexicon, not all RSSOP priority/tie-breaks, end groups or stereochemical nomenclature.'}

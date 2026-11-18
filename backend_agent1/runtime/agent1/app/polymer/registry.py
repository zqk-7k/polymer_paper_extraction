"""Importable, versioned registry. No fixture/test files are read at runtime."""
from __future__ import annotations
import json,re,sqlite3,time
from pathlib import Path
from .common import ROOT,key,stable_json,fail
from .chemistry import canonicalize
from .name_rules import EXTRA,systematic
from .family_rules import extended_systematic
from .queue_rules import resolve_source, name_diagnostic
from .repair_candidates import (REPAIR_CANDIDATE_STATUS, VERSION as REPAIR_VERSION,
                                DeclaredRepairTable, propose_source_repairs)
from .external_candidates import CANDIDATE_STATUS, VERSION as CANDIDATE_TABLE_VERSION, ExternalCandidateTable
from .locant_variants import DeclaredVariantTable
from .advanced_names import resolve_source_v05
from .families_v07 import resolve_source_v07
from .expansion_v08 import source as resolve_source_v08
from .heterocycles_v09 import source as resolve_source_v09
from . import parse_levers

def normalize_alias(s):return re.sub(r'[ \t\r\n\u00a0]+',' ',s.strip())

def local_rule_chain(name):
    """Bounded in-repo name grammar; ``(smiles, rule_id)`` or ``None``.

    Single source of truth for the local rule order, shared by ``Registry`` and
    by the declared-repair builder, so a declared repair can never resolve a
    name that the bounded grammar itself would not accept.
    """
    return (systematic(name) or extended_systematic(name) or resolve_source(name)
            or resolve_source_v05(name) or resolve_source_v07(name)
            or resolve_source_v08(name) or resolve_source_v09(name))

class Registry:
    def __init__(self,path=None,load_seed=True,external_candidates=None,
                 declared_variants=None,declared_repairs=None):
        self.path=str(path or ':memory:');self.db=sqlite3.connect(self.path,check_same_thread=False)
        # The operator switch is read here, once, so every construction path
        # (Kernel, tools, tests) sees the same levers.  With nothing switched on
        # this is {}, and an explicit keyword always wins over the environment.
        options=parse_levers.registry_options()
        explicit={'external_candidates':external_candidates,'declared_variants':declared_variants,
                  'declared_repairs':declared_repairs}
        options={**options,**{k:v for k,v in explicit.items() if v is not None}}
        external_candidates=options.get('external_candidates')
        declared_variants=options.get('declared_variants')
        declared_repairs=options.get('declared_repairs')
        # Opt-in, read-only external-parser candidates.  None keeps the previous
        # resolution namespace exactly as it was; policy and red lines are in
        # docs/ADR-003-external-parser-candidate-bindings.md.
        self.external=(external_candidates if isinstance(external_candidates,ExternalCandidateTable)
                       else ExternalCandidateTable(external_candidates)) if external_candidates else None
        # Opt-in declared tables (T3 locant/trade variants, T2 declared typo
        # rules).  Both default to None, so the default namespace is unchanged
        # and an old passport still replays.  Policy: docs/ADR-004.
        self.variants=(declared_variants if isinstance(declared_variants,DeclaredVariantTable)
                       else DeclaredVariantTable()) if declared_variants else None
        self.repairs=(declared_repairs if isinstance(declared_repairs,DeclaredRepairTable)
                      else DeclaredRepairTable(declared_repairs)) if declared_repairs else None
        self.db.execute('CREATE TABLE IF NOT EXISTS bindings (id TEXT PRIMARY KEY, alias TEXT, graph TEXT, source TEXT, review TEXT, active INTEGER, revision INTEGER)')
        self.db.execute('CREATE INDEX IF NOT EXISTS alias_idx ON bindings(alias,active)')
        self.db.execute('CREATE TABLE IF NOT EXISTS events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, time REAL, action TEXT, payload TEXT)')
        self.generation=0;self.cache={}
        if load_seed and not self.db.execute('SELECT 1 FROM bindings LIMIT 1').fetchone():
            seed=json.loads((ROOT/'data/seed_registry.json').read_text())
            self.import_records([{'aliases':x['aliases'],'smiles':x['reference_smiles'],'source':{'type':'previous_seed','id':x['monomer_id']},'review_status':'DRAFT'} for x in seed])
            self.import_records([{'aliases':a,'smiles':s,'source':{'type':'proposed_named_reference','version':'0.2'},'review_status':'DRAFT'} for a,s in EXTRA if s])
    def import_records(self,records):
        prepared=[]
        for r in records:
            names=r.get('aliases');s=r.get('smiles',r.get('reference_smiles'));g=canonicalize(s)
            if g['status']!='PARSED' or not isinstance(names,list) or not names or not all(isinstance(x,str) and x.strip() for x in names):raise ValueError('INVALID_REGISTRY_RECORD')
            source=r.get('source',{});review=r.get('review_status','DRAFT')
            if review not in ['DRAFT','REVIEWED']:raise ValueError('UNKNOWN_REVIEW_STATUS')
            if review=='REVIEWED' and (not r.get('reviewer') or not source):raise ValueError('REVIEW_REQUIRES_REVIEWER_AND_SOURCE')
            if review=='REVIEWED':source={**source,'reviewer':r['reviewer']}
            for alias in names:
                a=normalize_alias(alias);bid=key('binding/0.2',[a,g['molecule_key'],source])
                prepared.append((bid,a,g['isomeric_smiles'],stable_json(source),review,1,1))
        with self.db:
            for p in prepared:
                # Do not resurrect a revoked binding through re-import.
                self.db.execute('INSERT OR IGNORE INTO bindings VALUES (?,?,?,?,?,?,?)',p)
            self.db.execute('INSERT INTO events(time,action,payload) VALUES(?,?,?)',(time.time(),'IMPORT',stable_json({'records':len(records),'bindings_seen':len(prepared)})))
        self.generation+=1;self.cache.clear();return {'status':'PARSED','records_seen':len(records),'bindings_seen':len(prepared)}
    def revoke(self,binding_id,reason):
        if not reason:raise ValueError('REVOCATION_REASON_REQUIRED')
        with self.db:
            c=self.db.execute('UPDATE bindings SET active=0,revision=revision+1 WHERE id=?',(binding_id,))
            if c.rowcount!=1:raise ValueError('BINDING_NOT_FOUND')
            self.db.execute('INSERT INTO events(time,action,payload) VALUES(?,?,?)',(time.time(),'REVOKE',stable_json({'binding_id':binding_id,'reason':reason})))
        self.generation+=1;self.cache.clear()
        return {'status':'PARSED','binding_id':binding_id,'recompute_policy':'REPARSE_DEPENDENT_RECORDS_BEFORE_REUSE','generation':self.generation}
    def resolve(self,name):
        if not isinstance(name,str):return fail('NAME_MUST_BE_TEXT','INVALID')
        a=normalize_alias(name)
        if a in self.cache:return self.cache[a]
        records=self.db.execute('SELECT id,graph,source,review,active FROM bindings WHERE alias=?',(a,)).fetchall()
        # Tombstone blocks fallback: a revoked alias must not silently reappear via a rule.
        active=[r for r in records if r[4]];graphs={canonicalize(r[1])['molecule_key'] for r in active}
        if len(graphs)>1:out=fail('ALIAS_HAS_MULTIPLE_STRUCTURES','AMBIGUOUS',candidates=[{'binding_id':r[0],'smiles':r[1]} for r in active])
        elif active:
            r=next((r for r in active if r[3]=='REVIEWED'),active[0]);out={**canonicalize(r[1]),'name':name,'binding_id':r[0],'binding_status':r[3],'source':json.loads(r[2]),'reference_label':a}
        elif records:out=fail('ALIAS_REVOKED','NEEDS_DETAILS')
        else:
            # Declared naming variants (locant-group spellings and the two
            # verified dianhydride monomers) are opt-in exact-match rules, so
            # they are consulted before the naming diagnostics that would
            # otherwise short-circuit the bounded rule chain.
            variant=self._declared_variant(a,name)
            if variant is not None:
                out=variant
            else:
                # Keep low-level rule candidates available for COV-01 inspection,
                # but apply naming diagnostics at the public registry boundary.
                diagnostic = name_diagnostic(a)
                v = None if diagnostic else local_rule_chain(a)
                if v:
                    g=canonicalize(v[0]);out={**g,'name':name,'binding_status':'RULE_DERIVED_CANDIDATE','rule_id':v[1],'source':{'type':'bounded_name_grammar','version':'0.9' if v[1].startswith('LOCANTED-HETEROCYCLE/0.9') else '0.8' if v[1].startswith('NR-ROOTED-COMPOSITION/0.8') else '0.5'},'reference_label':a}
                else:
                    # The opt-in external-parser table is consulted after the local
                    # grammar and before the spelling-repair proposals, so a local
                    # rule always wins and a candidate never masquerades as one.
                    external=self._external_candidate(a,name)
                    if external is not None:
                        out=external
                    else:
                        # Opt-in declared typo rules resolve the repaired text
                        # through the same bounded grammar, and record the change.
                        repaired=self._declared_repair(a,name)
                        if repaired is not None:
                            out=repaired
                        else:
                            diagnostic=diagnostic or fail('NAME_NOT_IN_LOCAL_SCOPE')
                            refusal=self._variant_refusal(a)
                            if refusal:
                                # A recognised-but-refused name says why, without resolving.
                                diagnostic={**diagnostic,'naming_variant_refusal':refusal}
                            repairs=propose_source_repairs(a)
                            if repairs:
                                diagnostic={**diagnostic,'validated_repair_candidates':repairs}
                            out={**diagnostic,'name':name}
        self.cache[a]=out;return out
    def _external_candidate(self,alias,name):
        """Read-only candidate lookup; ``None`` if disabled or silent for *alias*."""
        if self.external is None:return None
        return self.external.resolve(alias,name=name)
    def _declared_variant(self,alias,name):
        """Declared-variant candidate, or ``None`` when disabled or not declared."""
        if self.variants is None:return None
        result=self.variants.lookup(alias)
        return {**result,'name':name} if result is not None else None
    def _variant_refusal(self,alias):
        """Refusal reason from the declared table; ``None`` when disabled."""
        return self.variants.refusal(alias) if self.variants is not None else None
    def _declared_repair(self,alias,name):
        """Resolve *alias* after a single declared typo fix, else ``None``.

        A declared repair is a *text* normalisation, so the repaired spelling is
        fed back through the same lookup chain the original spelling would have
        used: the bounded local grammar first, then (only when that opt-in table
        is loaded) the external-parser candidates.  The result keeps the raw text
        as its reference label, records the repair that was applied, and never
        claims a reviewed binding, a material identity or a preferred name.
        """
        if self.repairs is None:return None
        for proposal in self.repairs.proposals(alias):
            repair={'raw_text':alias,'repaired_text':proposal['proposed_text'],
                    'repair_rule_id':proposal['rule_id'],'change':proposal['change'],
                    'raw_preserved':True}
            resolved=local_rule_chain(proposal['proposed_text'])
            if resolved:
                graph=canonicalize(resolved[0])
                if graph.get('status')=='PARSED':
                    return {**graph,'name':name,'reference_label':alias,
                            'binding_status':REPAIR_CANDIDATE_STATUS,'rule_id':resolved[1],
                            'candidate_only':True,'review_status':'DRAFT','spelling_repair':repair,
                            'source':{'type':'declared_spelling_repair','version':REPAIR_VERSION,
                                      'repair_rule_id':proposal['rule_id'],
                                      'repaired_text':proposal['proposed_text'],
                                      'resolved_by_rule':resolved[1]},
                            'material_identity_issued':False,'polymerization_fact_established':False,
                            'preferred_iupac_name':None}
            external=self._external_candidate(proposal['proposed_text'],name)
            if external is not None:
                # A repaired spelling parsed by the opt-in candidate table: the
                # candidate status stays the external one, the repair is recorded.
                return {**external,'reference_label':alias,'spelling_repair':repair,
                        'source':{**(external.get('source') or {}),
                                  'repair_rule_id':proposal['rule_id'],
                                  'repaired_text':proposal['proposed_text'],'raw_preserved':True}}
        return None
    def external_candidate_summary(self):
        """Describe the loaded candidate table, or ``None`` when disabled."""
        return self.external.summary() if self.external is not None else None
    def declared_variant_summary(self):
        """Describe the declared-variant table, or ``None`` when disabled."""
        return self.variants.summary() if self.variants is not None else None
    def declared_repair_summary(self):
        """Describe the declared-repair table, or ``None`` when disabled."""
        return self.repairs.summary() if self.repairs is not None else None
    def lever_state(self):
        """Which opt-in parse levers this registry runs with, and their digests.

        A card has to be replayable against the exact namespace that produced
        it, so the passport records this whenever it is not the legacy one.
        ``default_namespace_unchanged`` means "this registry is on the legacy
        namespace", which since ADR-005/ADR-006 is *not* the shipped default:
        the three declared levers are on unless the environment turns them off.
        """
        state={'external_candidate_table':self.external_candidate_summary(),
               'declared_variant_table':self.declared_variant_summary(),
               'declared_repair_table':self.declared_repair_summary()}
        state['default_namespace_unchanged']=not any(state.values())
        state['namespace']=(parse_levers.LEGACY_NAMESPACE if state['default_namespace_unchanged']
                            else parse_levers.DEFAULT_NAMESPACE)
        return state
    def repair_candidates(self,name):
        """Inspect validated spelling repairs without mutating this registry."""
        if not isinstance(name,str):return []
        return propose_source_repairs(normalize_alias(name))
    def declared_repair_candidates(self,name):
        """Inspect declared repairs that the bounded grammar accepts, unapplied."""
        if self.repairs is None or not isinstance(name,str):return []
        out=[]
        for proposal in self.repairs.proposals(normalize_alias(name)):
            resolved=local_rule_chain(proposal['proposed_text'])
            graph=canonicalize(resolved[0]) if resolved else {}
            out.append({**proposal,'validated':bool(resolved) and graph.get('status')=='PARSED',
                        'resolved_by_rule':resolved[1] if resolved else None,
                        'candidate_graph':graph if resolved else None,
                        'candidate_only':True,'applied':False,'raw_preserved':True,
                        'review_status':'DRAFT','material_identity_issued':False,
                        'preferred_iupac_name':None})
        return out
    def all_bindings(self):
        return [dict(zip(['binding_id','alias','smiles','source_json','review_status','active','revision'],r)) for r in self.db.execute('SELECT * FROM bindings ORDER BY alias,id')]
    def snapshot(self):
        data=self.all_bindings();snap={'bindings':data,'snapshot_key':key('registry-snapshot/0.2',data),'generation':self.generation}
        if self.external is not None:
            # Candidate resolution is replayable only together with this hash.
            snap['external_candidate_table']={'path':str(self.external.path),'version':CANDIDATE_TABLE_VERSION,
                                             'source_sha256':self.external.source_sha256,
                                             'aliases':len(self.external.entries),'binding_status':CANDIDATE_STATUS}
        if self.variants is not None:
            # Same rule: an opt-in table is part of the resolution namespace, so
            # the snapshot has to name it and pin its digest.
            snap['declared_variant_table']=self.variants.summary()
        if self.repairs is not None:
            snap['declared_repair_table']=self.repairs.summary()
        return snap
    def close(self):self.db.close()

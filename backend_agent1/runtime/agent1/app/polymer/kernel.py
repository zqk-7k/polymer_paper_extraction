"""One authoritative runtime kernel shared by CLI, HTTP and test adapter.
This module never imports tests, reads fixture expectations or uses record IDs
to infer molecular structures. Catalog retrieval is optional and separate.
"""
from __future__ import annotations
from .registry import Registry
from .syntax import Parser
from .chemistry import canonicalize,compare_molecules,svg
from .periodic import canonicalize_unit,canonicalize_graph
from .reactions import derive,RULES
from .architecture import compile_architecture,compare_descriptions,validate_structured,compile_explicit_periodic_sequence
from .naming import source_name,name_from_unit
from .validation import validate_formula,validate_composition,bind_composition
from .providers import OpsinProvider
from .external_providers import BigSMILESProvider,PubChemCactusProvider
from .pipeline import from_parsed
from .common import fail,ROOT
from .conventions import apply as apply_conventions
from .finite_chains import compile_finite_chain,end_group_contexts

class Kernel:
    def __init__(self,registry=None):
        # The declared parse levers (T1/T2/T3) are on by default; Registry reads
        # the operator switch itself, so a caller never passes them in and an
        # explicit value always wins.  See docs/ADR-004 and docs/ADR-005.
        self.registry=registry or Registry(ROOT/'data/registry.sqlite' if (ROOT/'data/registry.sqlite').exists() else None);self.parser=Parser(self.registry);self.provider=OpsinProvider();self.bigsmiles=BigSMILESProvider();self.public=PubChemCactusProvider()
    def parse(self,x,enrich=False):
        r=self.parser.parse(x.get('name'),**{k:v for k,v in x.items() if k!='name'})
        r['end_group_contexts']=end_group_contexts(r)
        if not x.get('formation') and not x.get('formation_by_occurrence'):
            r=apply_conventions(r,x.get('interpretation_policy','evidence_only'))
        if x.get('composition') is not None:
            c=bind_composition(x['composition'],r.get('components',[]));r['composition_validation']=c
            if c['status']!='PARSED':r['status']=c['status'];r['reason_code']=c['reason_code']
        if x.get('formation') or x.get('formation_by_occurrence'):
            r['product_compilation']=from_parsed(r,x)
            p=r['product_compilation'].get('periodic',{})
            if p.get('status')=='PARSED' and r.get('semantic_projection'):
                r['semantic_projection']['constitution_key']=p['periodic_graph_key']
                r['semantic_projection']['constitution_support']='EXPLICIT_FORMATION_FACTS'
        if enrich:
            r['architecture']=compile_architecture(r)
            r['naming']=source_name(r)
            # Only explicit product units enter this structure-naming path.
            for leaf in r.get('components',[]):
                if leaf['kind']=='unit':leaf['structure_naming']=name_from_unit(leaf['unit']['unit_smiles'])
        return r
    def dispatch(self,operation,inputs):
        if not isinstance(inputs,dict):return fail('INPUT_OBJECT_REQUIRED','INVALID')
        if operation in ('create_passport','facts_to_passport'):
            from .passport import create_passport
            return create_passport(self,{'naming_profile':'frozen-name-candidate/0.7.0',**inputs})
        if operation=='text_to_passport':
            from .text_frontend import text_to_passport
            return text_to_passport(self,{'naming_profile':'frozen-name-candidate/0.7.0',**inputs})
        if operation=='text_to_identity':
            from .identity_flow import build_identity
            return build_identity(self,{'naming_profile':'frozen-name-candidate/0.7.0',**inputs})
        if operation=='main_identity_flow':
            from .main_flow import run_main_flow
            return run_main_flow(self, inputs)
        if operation=='rule_registry':
            from .rule_registry import list_rules
            return list_rules(inputs.get('applies_to'))
        if operation=='validate_passport':
            from .passport import validate_passport
            return validate_passport(inputs.get('passport'))
        if operation=='upgrade_passport_naming':
            from .naming_upgrade import upgrade_passport_naming
            return upgrade_passport_naming(inputs.get('passport'))
        if operation=='naming_diagnostics':
            from .naming_upgrade import naming_diagnostics
            return naming_diagnostics(inputs.get('passport'))
        if operation=='name_source_graph':
            from .graph_naming_v09 import name_source
            return name_source(inputs.get('smiles'))
        if operation=='name_unit_graph':
            from .graph_naming_v09 import name_unit
            return name_unit(inputs.get('smiles'))
        if operation=='name_from_passport':
            from .passport import name_from_passport
            return name_from_passport(inputs.get('passport'),inputs.get('mode','source'))
        if operation=='compare_passports':
            from .passport import compare_passports
            return compare_passports(inputs.get('left'),inputs.get('right'))
        if operation=='name_with_end_groups':
            from .end_naming import name_with_end_groups
            return name_with_end_groups(inputs)
        if operation=='catalog_to_passport':
            from .catalog_passport import catalog_to_passport
            return catalog_to_passport(self,inputs)
        if operation=='document_to_passports':
            from .document_frontend import document_to_passports
            return document_to_passports(self,inputs)
        if operation=='compile_finite_chain':return compile_finite_chain(inputs)
        if operation=='inspect_end_groups':
            parsed=self.parse({'name':inputs.get('name')})
            return {'status':parsed['status'],'contexts':parsed['end_group_contexts'],'parsed':parsed,'exact_material_identity':False}
        if operation=='resolve_monomer':return self.registry.resolve(inputs.get('name'))
        if operation=='resolve_name_opsin':return self.provider.resolve(inputs.get('name',''))
        if operation=='parse_bigsmiles':return self.bigsmiles.parse(inputs.get('notation',''))
        if operation=='match_bigsmarts':return self.bigsmiles.match(inputs.get('notation',''),inputs.get('pattern',''))
        if operation=='pubchem_resolve':return self.public.pubchem_name(inputs.get('name',''),allow_network=bool(inputs.get('allow_network',False)))
        if operation=='cactus_resolve':return self.public.cactus_name(inputs.get('name',''),allow_network=bool(inputs.get('allow_network',False)))
        if operation=='canonicalize_molecule':return canonicalize(inputs.get('smiles'))
        if operation=='compare_molecules':return compare_molecules(inputs.get('left'),inputs.get('right'))
        if operation in ('parse_polymer','parse_catalog_name'):return self.parse(inputs)
        if operation=='analyze':return self.parse(inputs,enrich=True)
        if operation=='enumerate_pair_candidates':
            from .pair_candidates import enumerate_pair
            return enumerate_pair(inputs)
        if operation=='compile_local_contexts':
            from .local_contexts import compile_contexts
            return compile_contexts(self.parse({'name':inputs.get('name')}),inputs)
        if operation=='local_contexts':
            from .local_contexts import discover_contexts
            contexts,barriers=discover_contexts(self.parse({'name':inputs.get('name')}))
            return {'status':'PARSED','contexts':contexts,'barriers':barriers,'whole_constitution_key':None}
        if operation=='compile_source_pools':
            from .source_pools import compile_pools
            return compile_pools(self.parse({'name':inputs.get('name')}),inputs)
        if operation=='compare_constitution_models':
            a=self.parse({'name':inputs.get('left'),'interpretation_policy':'idealized_common_chain'})
            b=self.parse({'name':inputs.get('right'),'interpretation_policy':'idealized_common_chain'})
            ak=a.get('semantic_projection',{}).get('constitution_key');bk=b.get('semantic_projection',{}).get('constitution_key')
            return {'status':'PARSED' if ak and bk else 'PARTIAL','relation':('SAME_IDEALIZED_CONSTITUTION' if ak==bk else 'DIFFERENT_IDEALIZED_CONSTITUTIONS') if ak and bk else 'UNRESOLVED','scope':'idealized_unoriented_achiral_constitution','left':a,'right':b,'exact_material_identity':False}
        if operation=='compare_names':return compare_descriptions(self.parser,inputs.get('left'),inputs.get('right'))
        if operation=='derive_repeat_fragment':
            r=derive(inputs);r['exact_constitution_identity']=False
            if r['status']=='PARSED':r['naming']=name_from_unit(r['repeat_smiles'])
            return r
        if operation=='canonicalize_periodic_graph':return canonicalize_graph(inputs.get('graph',{}))
        if operation=='canonicalize_unit':return canonicalize_unit(inputs.get('smiles'))
        if operation=='name_from_unit':return name_from_unit(inputs.get('smiles'))
        if operation=='iupac_rule_trace':
            from .iupac_rules import trace
            return trace(self,inputs)
        if operation=='name_from_ast':
            from .naming import render_ast
            return {'status':'PARSED','name':render_ast(inputs['ast']),'name_kind':'AST_RENDERING_NOT_FULL_CONFORMANCE'}
        if operation=='validate_formula':
            r=validate_formula(inputs);r['proves_identity']=False
            r['formula_assessment']={'FORMULA_MISSING':'MISSING','FORMULA_SCOPE_OR_COMPONENT_BINDING_REQUIRED':'SCOPE_UNRESOLVED'}.get(r.get('reason_code'),r.get('decision','INDETERMINATE'))
            return r
        if operation=='validate_composition':return validate_composition(inputs)
        if operation=='validate_architecture':return validate_structured(inputs.get('tree'))
        if operation=='compile_periodic_sequence':return compile_explicit_periodic_sequence(inputs)
        if operation=='mapped_residue':
            from .explicit_mapped_chemistry import residue
            return residue(inputs)
        if operation=='capabilities':return self.capabilities()
        return fail('OPERATION_NOT_IMPLEMENTED',operation=operation)
    def capabilities(self):
        return {'status':'PARSED','version':'0.9.0','recommended_naming_profile':'frozen-name-candidate/0.9.0','reaction_rules':sorted(RULES),'registry_bindings':len(self.registry.all_bindings()),
                'periodic_graph_scope':'ACHIRAL_1D_SINGLE_BRIDGE_CHAIN','name_profiles':['SOURCE_AST_RENDERING','BOUNDED_CU_GRAPH_TO_CANDIDATE','FROZEN_PASSPORT_RENDERING'], 'passport_schema':'polymer-passport/0.7', 'text_frontend':'BOUNDED_SINGLE_AND_MULTI_OBJECT_ZH_EN',
                'opsin':self.provider.probe(),'external_providers':{'bigsmiles':self.bigsmiles.version,'pubchem_cactus':self.public.version,'network_default':'disabled'},'interpretation_profiles':['evidence_only','idealized_common_chain'], 'full_iupac_conformance':False,'independent_chemical_accuracy':None,
                'identity_flow':'text-identity/1.0','identity_layers':['entity','occurrence','claim'],'rule_registry':'polymer-rule-registry/1.0',
                'operations':['text_to_identity','identity_search','identity_query','entity_search','candidate_evidence','review_queue_search','rule_registry'],
                'model_adapter':'not_configured','not_implemented':['complete_IUPAC_preferred_nomenclature','periodic_stereo_frames','general_ladders_and_network_graphs','automatic_unique_material_identification_from_light_catalog']}

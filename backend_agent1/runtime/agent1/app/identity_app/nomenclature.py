"""Explicit evidence-scoped naming. Never infer a product graph from a source.

The declaration is part of the material hash. Old passports and the 1.1 naming
namespace remain replayable. All chemical comparisons use the existing Kernel.
"""
from copy import deepcopy
import re
from polymer.supported_naming import RETAINED_MONOMERS

CONTRACT='identity-evidence-nomenclature/1.0'
CURRENT_CONTRACT='identity-evidence-nomenclature/1.1'
STRUCTURE_CONTRACT='identity-evidence-nomenclature/1.2'
SCOPE_CONTRACT='identity-evidence-nomenclature/1.3'
COMPOSITION_CONTRACT='identity-evidence-nomenclature/1.4'
from .sequence_nomenclature import CONTRACT as SEQUENCE_CONTRACT
MODIFIED_RULES='https://doi.org/10.1515/pac-2014-0610'
GUIDE='https://iupac.org/wp-content/uploads/2019/07/140-Brief-Guide-to-Polymer-Nomenclature-Web-Final-d.pdf'

def substituent_order_key(text):
    """Latin substituent names: letters precede numeric/heteroatom locants.

    Retain the complete chemical name in output. This is a formatting rule,
    not preferred-name certification or a structure/name generator.
    """
    name=text.casefold()
    letters=re.sub(r"\b[nosp](?:['′]+)?(?=[,-])",'',name)
    letters=re.sub(r"\b\d+[a-z]*['′]*(?=[,)-]|$)",'',letters)
    letters=re.sub(r'[^a-z]','',letters)
    return letters,tuple(int(x) for x in re.findall(r'\d+',name)),name

def enclosed(text):
    # Bicyclo/spiro bridge locants are intrinsic chemical notation, not an
    # enclosing-mark layer of the polymer/source expression.
    marks=re.sub(r'(?:bicyclo|spiro)\[[0-9.]+\]','',text)
    left,right=('{','}') if '[' in marks else ('[',']') if '(' in marks else ('(',')')
    return left+text+right

def assess(kernel,m,candidate,seen=None):
    d=m.get('nomenclature_declaration')
    if not d:return None
    if d.get('contract') in ('identity-model-nomenclature/1.0','identity-model-nomenclature/1.1'):
        from .model_nomenclature import assessment
        return assessment(m,candidate)
    result={'contract':CONTRACT,'status':'NEEDS_EVIDENCE','primary':None,'formal_name':None,
            'preferred_iupac_name':None,'full_iupac_conformance':False,'independent_review':'NOT_REVIEWED',
            'source_url':GUIDE,'scope':'reported_source_and_identity_qualifiers',
            'checks':[],'remaining':deepcopy(m.get('unknowns',[])),
            'next_steps':[],'identity_qualifiers':deepcopy(d.get('identity_qualifiers',[]))}
    seen=set(seen or ())
    if m['id'] in seen:return {**result,'reason_code':'CYCLIC_NOMENCLATURE_DEPENDENCY'}
    seen.add(m['id'])
    def fail(reason):return {**result,'reason_code':reason}
    if d.get('contract') not in (CONTRACT,CURRENT_CONTRACT,STRUCTURE_CONTRACT,SCOPE_CONTRACT,COMPOSITION_CONTRACT,SEQUENCE_CONTRACT):return fail('UNKNOWN_NOMENCLATURE_CONTRACT')
    upgraded=d.get('contract') in (CURRENT_CONTRACT,STRUCTURE_CONTRACT,SCOPE_CONTRACT,COMPOSITION_CONTRACT,SEQUENCE_CONTRACT)
    result['contract']=d['contract']
    if d.get('contract')==COMPOSITION_CONTRACT and d.get('kind')!='matrix_with_components':
        return fail('MATRIX_COMPOSITION_CONTRACT_KIND_REQUIRED')
    if d.get('contract')==SEQUENCE_CONTRACT and d.get('kind') not in ('source_polymer','block_copolymer'):
        return fail('SEQUENCE_CONTRACT_KIND_REQUIRED')
    if d.get('contract')==SEQUENCE_CONTRACT:
        from .adoption import CURRENT_POLICY
        if candidate.get('adoption_policy')!=CURRENT_POLICY:return fail('EXPLICIT_SEQUENCE_ADOPTION_POLICY_REQUIRED')
        if m.get('kind') not in ('polymer','prepolymer'):return fail('SEQUENCE_POLYMER_MATERIAL_REQUIRED')
    if upgraded:
        basis=d.get('evidence_basis','source_supported')
        bases=('source_supported','broader_scope','most_likely_hypothesis') + (('feasible_hypothesis',) if d['contract'] in (SCOPE_CONTRACT,COMPOSITION_CONTRACT,SEQUENCE_CONTRACT) else ())
        if basis not in bases:return fail('NAMING_EVIDENCE_BASIS_REQUIRED')
        hypotheses=d.get('hypotheses',[])
        if basis in ('most_likely_hypothesis','feasible_hypothesis') and (not hypotheses or any(not isinstance(h,dict) or not h.get('statement') or not h.get('reason') or not h.get('source_refs') or not set(h['source_refs']).issubset(set(d.get('source_refs',[]))) for h in hypotheses)):
            return fail('EXPLICIT_SOURCED_NAMING_HYPOTHESES_REQUIRED')
        result.update(evidence_basis=basis,hypotheses=deepcopy(hypotheses),
                      quantity_scope='source quantities preserved separately; feed is not incorporated composition')
    if not d.get('source_refs') or not set(d['source_refs']).issubset(set(m.get('source_refs',[]))):
        return fail('DECLARATION_SOURCE_REFS_REQUIRED')
    def child(mid):
        other=candidate['materials'].get(mid)
        if not other:return None
        return assess(kernel,other,candidate,seen)
    def linked(mid):
        return any(mid in (x.get('material_id'),x.get('source_molecule_material_id')) for x in m.get('components',[])) or any(
            r.get('from_material_id')==mid and r.get('to_material_id')==m['id'] for r in candidate.get('relations',[]))
    def finite(mid,text=None):
        other=candidate['materials'].get(mid)
        if not other:return None
        name=text or (other.get('most_likely_name') or {}).get('text')
        gs=[candidate['graphs'][g] for g in other.get('graph_ids',[]) if g in candidate['graphs']]
        if len(gs)!=1 or gs[0]['scope']!='finite_molecule':return None
        return checked_finite(name,gs[0],other)
    def checked_finite(text,g,owner):
        for link in owner.get('tool_evidence',[]):
            r=candidate.get('tool_receipts',{}).get(link.get('receipt_id'),{})
            p=r.get('result',{}).get('result',{})
            if r.get('operation')!='resolve' or r.get('input',{}).get('name')!=text or p.get('status')!='PARSED':continue
            check=kernel.dispatch('compare_molecules',{'left':g['canonical_smiles'],'right':p.get('isomeric_smiles') or p.get('candidate_smiles')})
            result['checks'].append({'rule':'finite source name to graph','name':text,'graph_id':g['id'],
                                     'receipt_id':r['id'],'relation':check.get('relation')})
            if check.get('status')=='PARSED' and check.get('relation')=='EQUAL':return text
        return None
    kind=d.get('kind')
    if kind=='matrix_with_components':
        from .adoption import CURRENT_POLICY, SOURCE_POLICY
        if d.get('contract')!=COMPOSITION_CONTRACT or candidate.get('adoption_policy') not in (SOURCE_POLICY, CURRENT_POLICY):
            return fail('EXPLICIT_MATRIX_COMPOSITION_CONTRACT_REQUIRED')
        if d.get('combination')!='physical' or m.get('constitution'):
            return fail('MATRIX_FORMULATION_IS_NOT_COVALENT_REPEAT')
        mid=d.get('base_material_id');base=child(mid)
        if not base or not base.get('formal_name') or not base.get('primary_matches_display'):
            return fail('MATRIX_POLYMER_NAME_NOT_READY')
        if candidate['materials'][mid].get('kind') not in ('polymer','prepolymer'):
            return fail('POLYMER_MATRIX_REQUIRED')
        cs=m.get('components',[]);ids=[x.get('material_id') for x in cs]
        if mid not in ids or len(ids)<2 or len(set(ids))!=len(ids):return fail('EXPLICIT_FORMULATION_COMPONENTS_REQUIRED')
        named=[]
        for c in cs:
            owner=candidate['materials'].get(c.get('material_id'))
            if not owner:return fail('FORMULATION_COMPONENT_NOT_FOUND')
            if c['material_id']==mid:name=base['formal_name']
            else:
                if owner.get('kind') not in ('component','monomer','oligomer'):return fail('SINGLE_POLYMER_WITH_FINITE_COMPONENTS_REQUIRED')
                name=finite(c['material_id'])
                if not name:return fail('FINITE_FORMULATION_NAME_GRAPH_NOT_READY')
            if not any(r.get('type')=='formulation_component' and r.get('from_material_id')==c['material_id'] and r.get('to_material_id')==m['id'] for r in candidate.get('relations',[])):
                return fail('TYPED_FORMULATION_LINK_REQUIRED')
            named.append({**deepcopy(c),'name':name})
        result.update(status='MATRIX_IDENTITY_AND_COMPONENTS_SUPPORTED',primary=base['formal_name'],formal_name=base['formal_name'],
                      scope='polymer matrix identity; physical formulation separately named and qualified, no single whole-material IUPAC name',
                      composition_components=named,whole_material_single_iupac_name=False)
        result['identity_qualifiers'].append({'text':'physical formulation; primary names the polymer matrix only',
            'source_refs':d['source_refs'],'components':named})
        result['checks'].append({'rule':'explicit matrix and finite name/graph/role bindings, quantities preserved without inferring incorporation',
                                'matrix_material_id':mid,'whole_product_constitution_inferred':False})
        if base.get('hypotheses'):result.setdefault('hypotheses',[]).extend(base['hypotheses'])
    elif kind=='structure_polymer':
        if d.get('contract')!=STRUCTURE_CONTRACT:return fail('EXPLICIT_STRUCTURE_CONTRACT_REQUIRED')
        gid=d.get('graph_id');g=candidate['graphs'].get(gid);constitution=m.get('constitution') or {}
        if not g or gid not in m.get('graph_ids',[]) or g['scope']!='repeat_unit' or constitution.get('graph_id')!=gid or constitution.get('coverage')!='ideal_repeat':return fail('STRUCTURE_WHOLE_REPEAT_REQUIRED')
        from rdkit import Chem
        raw=Chem.MolFromSmiles(g['canonical_smiles'])
        if raw is None or any(a.GetIsotope() or a.GetFormalCharge() or a.GetChiralTag()!=Chem.ChiralType.CHI_UNSPECIFIED for a in raw.GetAtoms()) or any(b.GetStereo()!=Chem.BondStereo.STEREONONE for b in raw.GetBonds()):return fail('SPECIFIED_CHEMISTRY_OUTSIDE_STRUCTURE_PROFILE')
        r=candidate.get('tool_receipts',{}).get(d.get('name_graph_receipt_id'),{})
        from pathlib import Path
        from .storage import file_hash
        receipt_path=Path(r.get('receipt_path',''))
        if not r.get('stored_from_actual_operation') or not receipt_path.is_file() or file_hash(receipt_path)!=r.get('sha256'):return fail('ACTUAL_CURRENT_STRUCTURE_NAME_ROUNDTRIP_REQUIRED')
        named=(r.get('result') or {}).get('result') or {};rt=named.get('roundtrip') or {}
        from polymer.periodic import canonicalize_unit
        key=canonicalize_unit(g['canonical_smiles']).get('periodic_graph_key')
        if r.get('operation')!='name_graph' or r.get('exit_code')!=0 or r.get('input',{}).get('graph_id')!=gid or named.get('contract')!='iupac-regular-unit-graph-candidate/1.0' or rt.get('status')!='GRAPH_MATCH' or not key or rt.get('target_key')!=key or rt.get('named_key')!=key:return fail('ACTUAL_CURRENT_STRUCTURE_NAME_ROUNDTRIP_REQUIRED')
        primary=(named.get('primary') or {}).get('text')
        if not primary:return fail('STRUCTURE_NAME_MISSING')
        source=d.get('source_declaration')
        if not isinstance(source,dict) or source.get('contract') not in (CONTRACT,CURRENT_CONTRACT):return fail('SOURCE_NAME_ALTERNATIVE_REQUIRED')
        source_check=assess(kernel,{**m,'nomenclature_declaration':source},candidate,seen-{m['id']})
        if not source_check or not source_check.get('formal_name'):return fail('SOURCE_NAME_ALTERNATIVE_UNSUPPORTED')
        result.update(status='STRUCTURE_NAME_SUPPORTED',primary=primary,formal_name=primary,
                      scope='declared_ideal_constitution_with_preserved_sample_unknowns',structure_rule_contract=named['contract'],
                      source_alternative={'text':source_check['formal_name'],'assessment':source_check},
                      checks=[{'rule':'complete named unit to periodic graph','receipt_id':r['id'],'relation':'EQUAL','target_key':key}],
                      next_steps=['理想构成及假设已核对；实物微结构、端基、掺杂和完整优选认证仍按来源保留。'])
    elif kind=='source_polymer':
        names=[]
        for source in d.get('monomers',[]):
            if source.get('material_id'):
                mid=source['material_id']
                if not linked(mid):return fail('SOURCE_MATERIAL_LINK_REQUIRED')
                name=finite(mid)
            else:
                name=source.get('name','')
                if name.lower() not in RETAINED_MONOMERS|{'ethene','propene'} or not source.get('source_refs') or not set(source['source_refs']).issubset(set(d['source_refs'])):
                    return fail('UNVERIFIED_MONOMER_SOURCE')
                parsed=kernel.parse({'name':'poly'+enclosed(name),'interpretation_policy':'evidence_only'})
                result['checks'].append({'rule':'retained source nomenclature','name':name,'kernel_status':parsed.get('status')})
                if parsed.get('status')!='PARSED':return fail('SOURCE_SYNTAX_UNSUPPORTED')
            if not name:return fail('SOURCE_NAME_GRAPH_NOT_VERIFIED')
            names.append(name)
        if not names:return fail('MONOMER_SOURCES_REQUIRED')
        seq=d.get('sequence','unspecified')
        if d['contract']==SEQUENCE_CONTRACT:
            from .sequence_nomenclature import source_sequence
            selected=source_sequence(d,m,names)
            if selected.get('reason_code'):return fail(selected['reason_code'])
            result['sequence_review']=selected
            connective=selected['connective']
        else:
            if len(names)>1 and seq!='unspecified' and not (upgraded and seq=='alternating' and len(names)==2):return fail('SEQUENCE_PROFILE_NOT_ENABLED')
            connective='-alt-' if seq=='alternating' else '-co-'
        # Complex source names get inner marks before co; unknown sequence never becomes ran/stat/per.
        if d['contract']==SEQUENCE_CONTRACT:connective='-'+connective+'-'
        body=names[0] if len(names)==1 else connective.join('('+n+')' if any(x in n for x in '()[] ') else n for n in names)
        text='poly'+enclosed(body)
        if d.get('tacticity'):
            if d['tacticity'] not in ('isotactic','syndiotactic','atactic'):return fail('TACTICITY_UNSUPPORTED')
            text=d['tacticity']+'-'+text
        result.update(status='SOURCE_NAME_SUPPORTED',primary=text,formal_name=text,
                      next_steps=['理想重复构成明确时可继续结构型命名；未定端基或链长不阻止理想聚合物命名。序列与立构只在相应证据范围内指定。'])
        result['checks'].append({'rule':'IUPAC brief guide §3.1/3.2','status':'PASS','product_constitution_inferred':False})
    elif kind=='block_copolymer':
        if d['contract']!=SEQUENCE_CONTRACT:return fail('EXPLICIT_BLOCK_CONTRACT_REQUIRED')
        from .sequence_nomenclature import block_name
        block=block_name(m,candidate,d,child)
        if block.get('reason_code'):return fail(block['reason_code'])
        for h in block.pop('hypotheses',[]):
            if h not in result.setdefault('hypotheses',[]):result['hypotheses'].append(h)
        result.update(block)
    elif kind in ('state','network','functionalized'):
        mid=d.get('base_material_id')
        if not linked(mid):return fail('BASE_MATERIAL_LINK_REQUIRED')
        base=child(mid)
        if not base or not base.get('formal_name'):return fail('BASE_NAME_NOT_SUPPORTED')
        result['checks'].append({'rule':'linked base material','material_id':mid,'assessment':base})
        if kind=='state':
            if not d.get('identity_qualifiers'):return fail('STATE_QUALIFIERS_REQUIRED')
            result.update(status='BASE_NAME_WITH_QUALIFIERS',primary=base['formal_name'],formal_name=base['formal_name'],
                          next_steps=['保留加工状态和分子量限定；如加工改变共价构成，须补证后另行命名。'])
        elif kind=='network':
            if m.get('kind')!='network':return fail('NETWORK_IDENTITY_REQUIRED')
            text='net-'+base['formal_name']
            result.update(status='SOURCE_NETWORK_SUPPORTED',primary=text,formal_name=text,
                          next_steps=['补交联位点、转化率、立构及连接拓扑；net 来源名不证明唯一网络结构。'])
        else:
            if not any(x.get('role') in ('covalently_incorporated_functionality','source_assigned_graft_functionality') for x in m.get('components',[])):
                return fail('COVALENT_FUNCTIONALITY_EVIDENCE_REQUIRED')
            result.update(status='QUALIFIED_DESCRIPTION',primary=m['most_likely_name']['text'],base_name=base['formal_name'],
                          next_steps=['确认孤立残基或聚合接枝链及连接原子；只有证实聚合侧链后才使用 -graft-poly(...)。',
                                      'MMI 路径需同时确定酯位、环酐结构及比例。'])
    elif upgraded and kind in ('modified','graft'):
        mid=d.get('base_material_id')
        if not linked(mid):return fail('BASE_MATERIAL_LINK_REQUIRED')
        base=child(mid)
        if not base or not base.get('formal_name'):return fail('BASE_NAME_NOT_SUPPORTED')
        result['checks'].append({'rule':'linked base identity','material_id':mid,'assessment':base})
        if kind=='modified':
            if d.get('topology')!='point_substituents':return fail('MOD_RULE_EXCLUDES_POLYMERIC_GRAFTS_AND_NETWORKS')
            groups=[]
            for sub in d.get('substituents',[]):
                gid=sub.get('graph_id');g=candidate['graphs'].get(gid,{});check=g.get('substituent_check',{})
                owner=sub.get('source_material_id')
                if not linked(owner) or not sub.get('source_refs') or not set(sub['source_refs']).issubset(set(d['source_refs'])):return fail('SUBSTITUENT_SOURCE_LINK_REQUIRED')
                r=candidate.get('tool_receipts',{}).get(check.get('receipt_id'),{})
                if gid not in m.get('graph_ids',[]) or check.get('status')!='GRAPH_MATCH' or check.get('name')!=sub.get('name') or r.get('operation')!='check_substituent' or r.get('exit_code')!=0:
                    return fail('SUBSTITUENT_NAME_GRAPH_RECEIPT_REQUIRED')
                groups.append(sub['name']);result['checks'].append({'rule':'IUPAC substituent/free-valence graph consistency',**check})
            if not groups:return fail('SUBSTITUENTS_REQUIRED')
            text='['+base['formal_name']+']-mod-'+';'.join(sorted(groups,key=substituent_order_key))
            result.update(status='MODIFIED_NAME_SUPPORTED',primary=text,formal_name=text,source_url=MODIFIED_RULES,
                          scope='modified polymer family; substituent positions and distribution unspecified',
                          next_steps=['用位点和接枝长度证据区分点取代与聚合支链；组成基准明确后再附组成限定。'])
            result['checks'].append({'rule':'IUPAC 2014 MP-2.5 Rule 5; simultaneous unspecified-site substituents','status':'PASS'})
        else:
            if d.get('topology')!='polymeric_side_chains':return fail('POLYMERIC_GRAFT_TOPOLOGY_REQUIRED')
            branches=[]
            if d.get('contract')==SCOPE_CONTRACT and d.get('branch_material_id'):
                branch_id=d['branch_material_id']
                def typed_link(owner,role):
                    return any(r.get('type')==role and r.get('from_material_id')==owner and r.get('to_material_id')==m['id'] for r in candidate.get('relations',[]))
                if not typed_link(mid,'graft_backbone_of') or not typed_link(branch_id,'graft_sidechain_of'):
                    return fail('TYPED_GRAFT_BACKBONE_AND_SIDECHAIN_REQUIRED')
                branch=child(branch_id)
                if not branch or not branch.get('formal_name') or not branch.get('primary_matches_display') or candidate['materials'][branch_id].get('kind') not in ('polymer','prepolymer'):
                    return fail('POLYMERIC_BRANCH_NAME_NOT_READY')
                branches.append(branch['formal_name'])
                result['checks'].append({'rule':'already-named polymeric sidechain identity','material_id':branch_id,'assessment':branch})
                if branch.get('hypotheses'):result.setdefault('hypotheses',[]).extend(branch['hypotheses'])
                if d.get('graft_sources'):return fail('BRANCH_IDENTITY_OR_FINITE_SOURCE_REQUIRED_NOT_BOTH')
            for item in d.get('graft_sources',[]):
                other=item.get('material_id')
                if not linked(other):return fail('GRAFT_SOURCE_LINK_REQUIRED')
                name=finite(other)
                if not name:return fail('GRAFT_SOURCE_NAME_GRAPH_NOT_VERIFIED')
                branches.append('poly'+enclosed(name))
            if len(branches)!=1:return fail('SINGLE_GRAFT_SOURCE_PROFILE_REQUIRED')
            text=base['formal_name']+'-graft-'+branches[0]
            result.update(status='GRAFT_NAME_SUPPORTED',primary=text,formal_name=text,
                          scope='source-based graft identity; branch length and positions unspecified',
                          next_steps=['测定聚合支链与单个加成残基比例、连接位点；当前来源型名字不指定支链长或端基。'])
            result['checks'].append({'rule':'IUPAC brief guide table 1: backbone first, polymeric branch second','status':'PASS'})
        if base.get('hypotheses'):result.setdefault('hypotheses',[]).extend(base['hypotheses'])
    elif kind=='blend':
        components=[x['material_id'] for x in m.get('components',[]) if x.get('material_id') and x.get('relation')=='physical_blend_component']
        if m.get('kind')!='blend' or len(components)<2:return fail('PHYSICAL_BLEND_COMPONENTS_REQUIRED')
        assessed=[child(mid) for mid in components]
        if any(not x or not x.get('primary') for x in assessed):return fail('BLEND_COMPONENT_NAME_NOT_READY')
        complete=all(x.get('formal_name') for x in assessed)
        text='-blend-'.join(x['formal_name'] or enclosed(x['primary']) for x in assessed)
        result.update(status='SOURCE_ASSEMBLY_SUPPORTED' if complete else 'QUALIFIED_ASSEMBLY',primary=text,
                      formal_name=text if complete else None,
                      next_steps=['组分名称与共混关系已保存；组成比的质量/物质的量基准仍须来源确认。']+
                        ([] if complete else ['先补全接枝相身份；-blend- 连接词成立不等于整个表达为完整 IUPAC 名。']))
        result['checks'].append({'rule':'IUPAC brief guide table 2: blend','components':components,'assessments':assessed})
        if upgraded:
            for a in assessed:
                if a.get('hypotheses'):result.setdefault('hypotheses',[]).extend(a['hypotheses'])
    elif kind=='finite_alternatives':
        names=[]
        declared=d.get('alternatives',[])
        if len(declared)<2 or {x.get('graph_id') for x in declared}!=set(m.get('graph_ids',[])):return fail('ALL_ALTERNATIVE_GRAPHS_REQUIRED')
        for alt in declared:
            g=candidate['graphs'].get(alt.get('graph_id'))
            if not g or g['scope']!='finite_molecule':return fail('FINITE_ALTERNATIVE_GRAPH_REQUIRED')
            name=checked_finite(alt.get('name'),g,m)
            if not name:return fail('ALTERNATIVE_NAME_GRAPH_NOT_VERIFIED')
            names.append({'name':name,'graph_id':g['id']})
        result.update(status='CANDIDATE_SET_VERIFIED',primary=None,alternatives=names,
                      next_steps=['用来源结构图/区域异构证据确定酯位；当前两个名字各自与图一致，尚不能选择唯一名称。'])
        if upgraded and d.get('selected_graph_id'):
            choice=next((x for x in names if x['graph_id']==d['selected_graph_id']),None)
            if not choice or result.get('evidence_basis')!='most_likely_hypothesis' or not d.get('selection_reason'):return fail('EXPLICIT_ALTERNATIVE_SELECTION_HYPOTHESIS_REQUIRED')
            result.update(status='HYPOTHESIS_NAME_SUPPORTED',primary=choice['name'],formal_name=choice['name'],
                          selected_graph_id=choice['graph_id'],selection_reason=d['selection_reason'])
    else:return fail('DECLARATION_KIND_UNSUPPORTED')
    if upgraded and result.get('hypotheses'):
        result['evidence_basis']='feasible_hypothesis' if d.get('contract') in (SCOPE_CONTRACT,COMPOSITION_CONTRACT,SEQUENCE_CONTRACT) and result.get('evidence_basis')=='feasible_hypothesis' else 'most_likely_hypothesis'
        result['source_identity_proven']=False
    if upgraded:result['conformance_scope']='bounded complete structure-name rules and periodic graph roundtrip; not full preferred nomenclature' if kind=='structure_polymer' else 'checked declared source/assembly/substituent rules; not full preferred nomenclature'
    result['primary_matches_display']=result.get('primary')==(m.get('most_likely_name') or {}).get('text')
    return result

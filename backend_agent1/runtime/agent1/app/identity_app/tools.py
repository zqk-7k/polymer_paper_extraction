"""One bounded source/chemistry/candidate tool surface. Writes only its job."""
import argparse, base64, json, os, re, time, uuid
from pathlib import Path
from copy import deepcopy
from .diagnostics import attach, failure_result
from .storage import APP, atomic, read, digest, file_hash, now, validate, material_hash
from polymer.kernel import Kernel
from polymer.registry import Registry
from polymer.passport import create_passport
from polymer.naming_service import NamingService
from polymer.structure_reconstructions import draw_identity
from rdkit import Chem
from rdkit.Chem import rdMolDescriptors
from .chemistry_checks import (CONTRACT as FOUNDATION, graph_profile, name_graph, finite_scope,
                              parser_check, compare_graphs, review_material, source_only_oligomer)

def ensure_refs(refs,index):
    valid={b['id'] for b in index.get('blocks',[])}|{'page:'+str(n) for n in range(1,index.get('page_count',0)+1)}|{'text:input'}
    if not isinstance(refs,list) or not refs or any(r not in valid for r in refs):raise ValueError('VALID_SOURCE_REFS_REQUIRED')
def kernel():
    os.environ['OPSIN_JAR']=str(APP/'third_party/opsin-core.jar')
    return Kernel(Registry())
def graph(spec):
    s=spec['smiles'];params=Chem.SmilesParserParams();params.parseName=False;params.removeHs=False
    mol=Chem.MolFromSmiles(s,params)
    if mol is None or not 0<mol.GetNumAtoms()<=350:raise ValueError('GRAPH_INVALID_OR_TOO_LARGE')
    scope=spec.get('scope')
    allowed=['repeat_unit','constitutional_unit','local_network','end_group','finite_molecule','component','oligomer','residue']
    if scope not in allowed:raise ValueError('GRAPH_SCOPE_REQUIRED:'+','.join(allowed))
    canonical=Chem.MolToSmiles(mol,canonical=True,isomericSmiles=True)
    ports=[{'index':a.GetIdx(),'map':a.GetAtomMapNum(),'degree':a.GetDegree()} for a in mol.GetAtoms() if a.GetAtomicNum()==0]
    if scope=='finite_molecule' and ports:raise ValueError('FINITE_MOLECULE_HAS_OPEN_PORTS')
    formula=rdMolDescriptors.CalcMolFormula(mol)
    periodic=None;rule=None;k=kernel()
    if scope=='repeat_unit' and len(ports)==2:
        from polymer.periodic import canonicalize_unit
        periodic=canonicalize_unit(canonical)
        rule=k.dispatch('name_from_unit',{'smiles':canonical})
    elif scope=='finite_molecule':
        rule=k.dispatch('name_source_graph',{'smiles':canonical})
    rendered=draw_identity(canonical)
    out={'input_smiles':s,'canonical_smiles':canonical,'scope':scope,'formula':formula,'formula_scope':'encoded '+scope+'; dummy attachment atoms shown as *; no finite-chain formula inferred','ports':ports,'atom_maps_preserved':True,'periodic':periodic,'deterministic_name':rule,'depiction':rendered,'source_refs':spec.get('source_refs',[]),'assumptions':spec.get('assumptions',[]),'unknowns':spec.get('unknowns',[]),'evidence_status':'COMPUTED_CANDIDATE_GRAPH','independent_review':'NOT_REVIEWED'}
    out['chemical_profile']=graph_profile(out)
    return out
def compact(value):
    if isinstance(value,list):return [compact(v) for v in value]
    if isinstance(value,dict):
        return {k:(v[:25] if isinstance(v,list) and k=='rule_trace' else compact(v)) for k,v in value.items() if k not in ('image','kernel_passport','kernel_naming')}
    return value

def stored_parser(m,job,current):
    name=(m.get('most_likely_name') or {}).get('text')
    records=list(current.get('tool_receipts',{}).values())
    records += [read(f,{}) for f in (Path(job)/'tool-events').glob('*.json')]
    for r in sorted(records,key=lambda x:x.get('finished_at',''),reverse=True):
        if r.get('operation')=='resolve' and r.get('input',{}).get('name')==name:
            out=r.get('result',{}).get('result',{})
            if out.get('status'):return out,r.get('id')
    return None

def check_binding(current,spec):
    mid=spec.get('material_id');gid=spec.get('graph_id')
    if mid and mid not in current['materials']:raise ValueError('MATERIAL_NOT_FOUND')
    if mid and gid and gid not in current['materials'][mid].get('graph_ids',[]):raise ValueError('GRAPH_NOT_OWNED_BY_MATERIAL')

def parser_for_review(m,job,current):
    if source_only_oligomer(m,current):return (None,None)
    saved=stored_parser(m,job,current)
    gs=[current['graphs'][g] for g in m.get('graph_ids',[]) if g in current['graphs']]
    if not saved and m['kind'] in ('component','monomer','oligomer') and len(gs)==1 and gs[0]['scope']=='finite_molecule' and (m.get('most_likely_name') or {}).get('text') and (m.get('most_likely_name') or {}).get('basis')!='material_expression':
        name=m['most_likely_name']['text']
        prep=execute('prepare_component',{'material_id':m['id'],'raw_name':m['label'],'full_name':name,
            'aliases':m.get('aliases',[]),'origin':'systematic_reexpression','reason':m['most_likely_name'].get('reason') or 'Primary-session supplied candidate name',
            'source_refs':m['source_refs'],'assumptions':m['most_likely_name'].get('assumptions',[])},job)
        result=execute('resolve',{'material_id':m['id'],'name':name,'preparation_receipt_id':prep['receipt_id'],
             'graph_id':gs[0]['id'],'scope':'finite_molecule'},job)
        # Preparation and binding write the same material. Keep the in-memory
        # reviewer synchronized instead of overwriting these receipts at commit.
        refreshed=read(Path(job)/'current.json')['materials'][m['id']]
        m['identity_preparations']=refreshed.get('identity_preparations',[])
        m['tool_evidence']=refreshed.get('tool_evidence',[])
        saved=(result['result'],result['receipt_id'])
    return saved

def _declared_alias_queries(preparation,name):
    """Return bounded source-declared spellings for a failed primary query.

    These are evidence-bearing spellings from the current paper only.  The
    helper deliberately does not consult the global registry or invent a
    synonym, and its results remain supplemental until a graph check agrees.
    """
    if not isinstance(preparation,dict):return []
    names=[preparation.get('raw_name'),*(preparation.get('aliases') or [])]
    return list(dict.fromkeys(x.strip() for x in names
        if isinstance(x,str) and x.strip() and x.strip()!=name and len(x.strip())<=300))

def bind_result(current,spec,op,result):
    mid=spec.get('material_id')
    if mid:
        if mid not in current['materials']:raise ValueError('MATERIAL_NOT_FOUND')
        current['materials'][mid].setdefault('tool_evidence',[]).append({
            'receipt_id':spec['_receipt_id'],'operation':op,'graph_id':spec.get('graph_id'),
            'query':spec.get('name'),'status':result.get('status') or result.get('result',{}).get('status')})

def _execute(op,spec,job):
    job=Path(job).resolve();run=read(job/'run.json',{});deadline=run.get('deadline_epoch',0)
    if deadline and time.time()>deadline:raise ValueError('WALL_CLOCK_BUDGET_EXHAUSTED')
    if deadline and time.time()>deadline-900 and op in ('resolve','public_lookup'):raise ValueError('CLOSEOUT_RESERVE_COMPONENT_LOOKUP_STOPPED')
    index=read(job/'source-index.json',{});current=read(job/'current.json',{'materials':{},'graphs':{},'observations':[],'withdrawals':[]})
    if op=='help':
        from .tool_help import tool_help
        return tool_help(current)
    if op=='snapshot':
        errors=validate(current,index,expected_reference_policy=run.get('material_reference_policy'))
        from .adoption import enabled
        projected=compact(current)
        if enabled(current) and not spec.get('full'):
            projected={k:current.get(k) for k in ('title','overview','adoption_policy','naming_policy')}
            projected['materials']={mid:{k:m.get(k) for k in ('id','label','kind','major','graph_ids','most_likely_name')}
                                   for mid,m in current['materials'].items()}
            for mid,m in current['materials'].items():
                projected['materials'][mid]['naming_review_receipt_id']=(m.get('nomenclature_declaration') or {}).get('review_receipt_id')
                projected['materials'][mid]['assessment']={k:(m.get('iupac_assessment') or {}).get(k) for k in ('status','formal_name','reason_code')}
            projected['history_count']=len(current.get('withdrawals',[]))
        return {'current':projected,'material_state_sha256':{i:material_hash(m,current['graphs'],current) for i,m in current['materials'].items()},'remaining_seconds':max(0,deadline-time.time()) if deadline else None,'validation_errors':errors,
            'next_action':'finish' if not errors else 'finalize after accepted naming proposals; fix substantive errors first'}
    if op=='read_source':
        if spec.get('page'):
            return {'page':spec['page'],'blocks':[b for b in index['blocks'] if b.get('page')==spec['page']]}
        if spec.get('refs'):
            return {'blocks':[b for b in index['blocks'] if b['id'] in spec['refs']]}
        return index
    if op=='crop':
        import fitz
        page=int(spec['page']);bbox=spec.get('bbox',[0,0,1,1]);doc=fitz.open(job/'source.pdf');p=doc[page-1]
        rect=fitz.Rect(bbox[0]*p.rect.width,bbox[1]*p.rect.height,bbox[2]*p.rect.width,bbox[3]*p.rect.height)
        dest=job/'crops'/('crop-'+uuid.uuid4().hex[:8]+'.png');dest.parent.mkdir(exist_ok=True);p.get_pixmap(matrix=fitz.Matrix(3,3),clip=rect).save(dest)
        return {'path':str(dest),'page':page,'bbox':bbox,'sha256':file_hash(dest),'status':'AVAILABLE_NOT_YET_MODEL_OBSERVED'}
    if op=='observe':
        page=spec.get('page');ensure_refs(['page:'+str(page)],index)
        if not spec.get('observation'):raise ValueError('ACTUAL_IMAGE_OBSERVATION_REQUIRED')
        item={**spec,'recorded_at':now(),'source_type':'MODEL_VISUAL_OBSERVATION_NOT_INDEPENDENT_FACT'};current['observations'].append(item)
        atomic(job/'current.json',current);return item
    if op=='prepare_constitution':
        from .constitution import prepare_sites
        check_binding(current,spec)
        g=current['graphs'][spec['graph_id']]
        if g['scope']!='finite_molecule':raise ValueError('FINITE_SOURCE_REQUIRED')
        return prepare_sites(g)
    if op=='derive_constitution':
        from .constitution import derive_selected
        ensure_refs(spec.get('source_refs'),index);check_binding(current,spec)
        g=current['graphs'][spec['graph_id']]
        if g['scope']!='finite_molecule':raise ValueError('FINITE_SOURCE_REQUIRED')
        out=derive_selected(kernel(),g,spec);edit=out['edit']
        if edit.get('status')!='CANDIDATE':return {**out,'status':edit.get('status','UNDETERMINED')}
        scope=spec.get('scope')
        if scope not in ('repeat_unit','component','residue') or scope=='repeat_unit' and len(spec['selected_site_ids'])!=2:
            raise ValueError('SELECTED_PRODUCT_SCOPE_REQUIRED')
        saved=execute('check_structure',{'id':spec['id'],'smiles':edit['residue_smiles'],'scope':scope,
            'source_refs':spec['source_refs'],'assumptions':spec.get('assumptions',[]),'unknowns':spec.get('unknowns',[])},job)
        current=read(job/'current.json');current['graphs'][spec['id']]['derivation']=compact(out)
        atomic(job/'current.json',current)
        return {**out,'status':'CANDIDATE','graph_id':spec['id'],'graph_receipt_id':saved['receipt_id']}
    if op=='prepare_component':
        ensure_refs(spec.get('source_refs'),index)
        mid=spec.get('material_id');check_binding(current,spec)
        raw=spec.get('raw_name');full=spec.get('full_name');aliases=spec.get('aliases',[])
        if not isinstance(raw,str) or not raw.strip() or not isinstance(full,str) or not 0<len(full)<=300:
            raise ValueError('RAW_AND_PREPARED_NAMES_REQUIRED')
        if spec.get('origin') not in ('source_definition','source_context','declared_synonym','systematic_reexpression') or not spec.get('reason'):
            raise ValueError('NAME_PREPARATION_ORIGIN_REASON_REQUIRED')
        if not isinstance(aliases,list) or not all(isinstance(x,str) for x in aliases) or len(aliases)>20:
            raise ValueError('BOUNDED_ALIASES_REQUIRED')
        # Read the existing registry through the same kernel; it is a candidate
        # source, never a replacement for this paper's identity or graph.
        k=kernel();lookups=[{'query':n,'result':k.registry.resolve(n)} for n in dict.fromkeys([raw,*aliases,full])]
        ambiguous=any(x['result'].get('status')=='AMBIGUOUS' for x in lookups)
        if ambiguous and not spec.get('selection_reason'):raise ValueError('AMBIGUOUS_ALIAS_SELECTION_REASON_REQUIRED')
        out={**deepcopy(spec),'contract':'component-name-preparation/1.0','status':'PREPARED',
             'registry_namespace':'frozen-name-candidate/0.9.0','registry_candidates':lookups,
             'source_fact':False,'independent_review':'NOT_REVIEWED','prepared_query':full}
        out.pop('_receipt_id',None)
        if mid:
            m=current['materials'][mid]
            m.setdefault('identity_preparations',[]).append({**out,'receipt_id':spec['_receipt_id']})
            atomic(job/'current.json',current)
        return out
    if op=='resolve':
        name=spec['name']
        if len(name)>300:raise ValueError('FINITE_COMPONENT_NAME_LIMIT')
        finite_scope({**spec,'scope':spec.get('scope','finite_molecule')},current['graphs'])
        check_binding(current,spec)
        if current.get('naming_policy')=='iupac-name-required/1.0' and spec.get('material_id') and not spec.get('preparation_receipt_id'):
            raise ValueError('COMPONENT_IDENTITY_PREPARATION_REQUIRED')
        preparation=None
        if spec.get('preparation_receipt_id'):
            r=read(job/'tool-events'/(spec['preparation_receipt_id']+'.json'),{})
            preparation=r.get('result',{})
            if r.get('operation')!='prepare_component' or r.get('exit_code')!=0 or preparation.get('prepared_query')!=name or r.get('input',{}).get('material_id')!=spec.get('material_id'):
                raise ValueError('PREPARED_NAME_RECEIPT_MISMATCH')
        # Reuse an actual successful exact query. New preparation and graph
        # review are still required; a failed parse is never a cache hit.
        from .evidence import receipts_for
        reused=None
        for r in reversed(list(receipts_for(job,current.get('tool_receipts')).values())):
            if r.get('operation')=='resolve' and r.get('exit_code')==0 and r.get('input',{}).get('name')==name and r.get('result',{}).get('result',{}).get('status')=='PARSED':
                if r.get('stored_from_actual_operation') and Path(r.get('receipt_path','')).is_file() and file_hash(r['receipt_path'])==r.get('sha256'):
                    reused=r;break
        k=kernel()
        result=deepcopy(reused['result']['result']) if reused else k.provider.resolve(name)
        out={'name':name,'tool':'LOCAL_OPSIN','result':result,'source_fact':False,'polymerization_fact':False,
             'preparation_receipt_id':spec.get('preparation_receipt_id'),'raw_name':preparation.get('raw_name') if preparation else None,
             'parser_calls':0 if reused else 1,'reused_parser_receipt_id':reused['id'] if reused else None}
        # A local-scope miss is not the end of a source-defined abbreviation.
        # Probe only the exact raw spelling and aliases declared in this paper;
        # keep every result visible and require a later graph check before any
        # model can adopt a supplemental name.
        if not reused and result.get('status') in ('UNSUPPORTED','INVALID'):
            supplemental=[];graph_checks=[]
            target=current.get('graphs',{}).get(spec.get('graph_id')) if spec.get('graph_id') else None
            for query in _declared_alias_queries(preparation,name):
                parsed=k.provider.resolve(query)
                item={'query':query,'parser_result':parsed,'source_declared':True}
                if target and parsed.get('status')=='PARSED':
                    item['graph_check']=parser_check(k,query,target,parsed)
                    graph_checks.append(item['graph_check'])
                supplemental.append(item)
            if supplemental:
                out['supplemental_results']=supplemental
                out['supplemental_graph_checks']=graph_checks
                out['parser_calls']+=len(supplemental)
        bind_result(current,spec,op,out)
        if spec.get('material_id'):atomic(job/'current.json',current)
        return out
    if op=='check_substituent':
        ensure_refs(spec.get('source_refs'),index);check_binding(current,spec)
        g=current['graphs'][spec['graph_id']]
        if g['scope'] not in ('residue','component') or len(g['ports'])!=1 or g['ports'][0]['degree']!=1:
            raise ValueError('MONOVALENT_SUBSTITUENT_GRAPH_REQUIRED')
        name=spec['name']
        if not isinstance(name,str) or not 0<len(name)<=300:raise ValueError('SUBSTITUENT_NAME_SIZE_LIMIT')
        k=kernel();parsed=k.provider.resolve_substituent(name)
        out={'contract':'iupac-substituent-graph/1.0','name':name,'graph_id':g['id'],'parser_result':parsed,
             'status':'UNSUPPORTED','source_fact':False,'independent_review':'NOT_REVIEWED'}
        if parsed.get('status')=='PARSED':
            p=Chem.SmilesParserParams();p.removeHs=False;p.parseName=False
            mol=Chem.MolFromSmiles(g['canonical_smiles'],p);port=next(a for a in mol.GetAtoms() if a.GetAtomicNum()==0)
            atom=port.GetNeighbors()[0];idx=port.GetIdx()
            # A free valence becomes exactly one radical for name-to-graph
            # comparison. Freeze H counts before removing the dummy atom.
            for a in mol.GetAtoms():
                if a.GetAtomicNum():a.SetNumExplicitHs(a.GetTotalNumHs());a.SetNoImplicit(True)
            atom.SetNumRadicalElectrons(atom.GetNumRadicalElectrons()+1)
            edit=Chem.RWMol(mol);edit.RemoveAtom(idx);radical=edit.GetMol();Chem.SanitizeMol(radical)
            target=Chem.MolToSmiles(radical,isomericSmiles=True)
            other=Chem.MolFromSmiles(parsed.get('isomeric_smiles') or parsed.get('candidate_smiles'),p)
            # Radical substituents have an explicit namespace. The frozen finite
            # molecule comparator continues rejecting radicals by default.
            for molecule in (radical,other):
                for a in molecule.GetAtoms():a.SetAtomMapNum(0)
            left=Chem.MolToSmiles(radical,isomericSmiles=True);right=Chem.MolToSmiles(other,isomericSmiles=True)
            out.update(status='GRAPH_MATCH' if left==right else 'MISMATCH',
                       comparison={'contract':'monovalent-substituent-graph/1.0','left':left,'right':right,
                                   'stereochemistry_isotopes_charge_radical_preserved':True})
            out['free_valence_radical_smiles']=target
        g['substituent_check']={**out,'receipt_id':spec['_receipt_id']}
        bind_result(current,spec,op,out);atomic(job/'current.json',current)
        return out
    if op=='public_lookup':
        g=finite_scope(spec,current['graphs'])
        if not spec.get('reason'):raise ValueError('LOOKUP_REASON_REQUIRED')
        check_binding(current,spec)
        provider=spec.get('provider','PubChem')
        if provider=='CAS':return {'status':'UNAVAILABLE','reason_code':'CAS_NOT_CONFIGURED','network_requests_attempted':0,'source_fact':False}
        if provider not in ('PubChem','CIR'):raise ValueError('PUBLIC_PROVIDER_NOT_ENABLED')
        query=g['canonical_smiles'] if g else spec['name'];kind='smiles' if g else 'name'
        if not isinstance(query,str) or not 0<len(query.strip())<=500:raise ValueError('PUBLIC_QUERY_SIZE_LIMIT')
        cache_key=digest({'provider':provider,'query':query,'kind':kind,'contract':FOUNDATION})
        cached=read(job/'tool-cache'/ (cache_key+'.json'))
        if cached:
            out={**cached,'cache_reused':True,'network_requests_attempted':0}
        else:
            previous=[read(p,{}) for p in (job/'tool-events').glob('*.json')]
            # A request counts even if result/cache persistence later fails.
            ledger={p.stem for p in (job/'network-attempts').glob('*.json')}
            attempted=len(ledger)+sum(r.get('result',{}).get('network_requests_attempted',
                      int(r.get('operation')=='public_lookup' and r.get('exit_code')==1))
                      for r in previous if r.get('id') not in ledger)
            if attempted>=12:out={'status':'DEFERRED','reason_code':'PUBLIC_REQUEST_BUDGET_EXHAUSTED','network_requests_attempted':0}
            else:
                k=kernel()
                atomic(job/'network-attempts'/(spec['_receipt_id']+'.json'),{'receipt_id':spec['_receipt_id'],
                       'provider':provider,'query':query,'query_kind':kind,'started_at':now(),'network_requests_attempted':1})
                result=(k.public.pubchem_smiles(query,allow_network=True) if g else k.dispatch('pubchem_resolve',{'name':query,'allow_network':True})) if provider=='PubChem' else k.public.cactus_representation(query,'smiles',allow_network=True,query_kind=kind)
                qualification={'status':'UNVERIFIED','reason_code':'SOURCE_IDENTITY_NOT_PROVEN'}
                if g and result.get('status')=='PARSED':
                    returned=(result.get('candidates') or [{}])[0].get('SMILES') or (result.get('candidates') or [{}])[0].get('IsomericSMILES') or result.get('smiles')
                    qualification=compare_graphs(k,g['canonical_smiles'],returned,'finite_molecule') if returned else {'status':'UNSUPPORTED','reason_code':'PUBLIC_STEREO_GRAPH_MISSING'}
                out={'provider':provider,'query':query,'query_kind':kind,'status':result.get('status'),
                     'result':result,'graph_check':qualification,'network_requests_attempted':1,
                     'cache_reused':False,'source_fact':False,'independent_review':'NOT_REVIEWED'}
                if result.get('status')=='PARSED':atomic(job/'tool-cache'/ (cache_key+'.json'),out)
        bind_result(current,spec,op,out)
        if spec.get('material_id'):atomic(job/'current.json',current)
        return out
    if op in ('profile','name_graph'):
        check_binding(current,spec);gid=spec['graph_id'];g=current['graphs'][gid]
        result=graph_profile(g) if op=='profile' else name_graph(kernel(),g,spec.get('rule_contract','iupac-supported-naming/1.1'))
        if op=='profile':g['chemical_profile']=result
        else:g['rule_profile_result']=result
        bind_result(current,spec,op,result);atomic(job/'current.json',current)
        return {'graph_id':gid,'result':result,'status':result.get('status')}
    if op=='declared_cru':
        check_binding(current,spec)
        parts=deepcopy(spec['parts'])
        for part in parts:ensure_refs(part.get('src'),index)
        k=kernel();result=NamingService(k).name_declared_cru(parts)
        checks=[]
        for part in parts:
            parsed=k.parser._resolve_unit(part['name'])
            checks.append({'name':part['name'],'status':'UNSUPPORTED','reason_code':parsed.get('reason_code')} if parsed.get('status')!='PARSED' else
                          {'name':part['name'],**compare_graphs(k,part['smiles'],parsed['unit_smiles'],'repeat_unit')})
        result['subunit_checks']=checks
        assembly=result.get('assembly',{})
        if spec.get('graph_id') and assembly.get('product_smiles'):
            result['target_graph_check']=compare_graphs(k,current['graphs'][spec['graph_id']]['canonical_smiles'],assembly['product_smiles'],'repeat_unit')
        if any(x['status']=='MISMATCH' for x in checks) or result.get('target_graph_check',{}).get('status')=='MISMATCH':
            result.update(status='MISMATCH',primary=None,reason_code='DECLARED_NAME_GRAPH_CONFLICT')
        result['validation_scope']='declared_subunit_consistency_only'
        result['subunit_preferred_nomenclature']='NOT_COMPLETED'
        bind_result(current,spec,op,result)
        if spec.get('material_id'):atomic(job/'current.json',current)
        return result
    if op=='review_naming':
        check_binding(current,spec)
        from .adoption import enabled
        if spec.get('adopt') and not enabled(current):
            raise ValueError('EXPLICIT_NEW_ADOPTION_POLICY_REQUIRED')
        from .model_nomenclature import review_proposal
        from .evidence import receipts_for
        context={**current,'tool_receipts':receipts_for(job,current.get('tool_receipts',{}))}
        result=review_proposal(kernel(),current['materials'][spec['material_id']],context,spec['proposal'])
        if spec.get('adopt') and result.get('formal_name'):
            # Explicit model request: bind the actual check and its exact text in
            # one save. The outer execute writes the receipt before final review.
            m=current['materials'][spec['material_id']]
            m['nomenclature_declaration']={'contract':spec['proposal'].get('contract','identity-model-nomenclature/1.0'),
                'proposal':deepcopy(spec['proposal']),'review_receipt_id':spec['_receipt_id']}
            m['most_likely_name']={**(m.get('most_likely_name') or {}),'text':result['formal_name'],
                'basis':'structure_based' if spec['proposal']['kind']=='structure_polymer' else 'source_based',
                'scope':spec['proposal'].get('name_scope') or spec['proposal']['kind'],
                'reason':spec['proposal']['selection_reason'],'assumptions':deepcopy(result['hypotheses']),
                'certified_preferred_iupac':False}
            result['candidate_name_saved']=True
        bind_result(current,spec,op,result);atomic(job/'current.json',current)
        return result
    if op=='verify_name':
        m=current['materials'][spec['material_id']]
        saved=parser_for_review(m,job,current)
        from .evidence import receipts_for
        context={**current,'tool_receipts':receipts_for(job,current.get('tool_receipts',{}))}
        result=review_material(kernel(),m,context,saved)
        m.update({key:value for key,value in result.items() if key!='input_sha256'})
        atomic(job/'current.json',current)
        return {'material_id':m['id'],'result':result['naming_verification'],'kernel_input_sha256':result['input_sha256']}
    if op in ('residue','edit'):
        from polymer.explicit_mapped_chemistry import residue, modification
        return (residue if op=='residue' else modification)(spec)
    if op=='assemble':
        from polymer.supplied_fragment_join import assemble
        return assemble(spec['fragments'],spec['links'])
    if op=='check_structure':
        ensure_refs(spec.get('source_refs'),index);out=graph(spec);gid=spec.get('id') or 'g-'+digest(out)[:12]
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',gid):raise ValueError('GRAPH_ID_INVALID')
        out['id']=gid
        image_data=base64.b64decode(out['depiction']['image'].split(',',1)[1]);image_path=job/'graph-images'/(gid+'-'+digest(out)[:10]+'.png');image_path.parent.mkdir(exist_ok=True);image_path.write_bytes(image_data)
        out['depiction']['image_file']=str(image_path.relative_to(job)).replace('\\','/')
        old=current['graphs'].get(gid)
        if old and old!=out:
            current['withdrawals'].append({'kind':'graph_revision','id':gid,'previous':old,'reason':spec.get('change_reason','Revised candidate'),'time':now()})
        current['graphs'][gid]=out;atomic(job/'current.json',current)
        return {'graph':compact(out),'material_state_sha256':{i:material_hash(m,current['graphs'],current) for i,m in current['materials'].items() if gid in m.get('graph_ids',[])}}
    if op=='bind_receipt':
        check_binding(current,spec)
        record=current.get('tool_receipts',{}).get(spec['receipt_id'])
        if not record or record.get('operation')!='resolve':raise ValueError('IMPORTED_RESOLVE_RECEIPT_REQUIRED')
        path=Path(record.get('receipt_path',''))
        if not path.is_file() or file_hash(path)!=record.get('sha256'):raise ValueError('RECEIPT_FILE_HASH_MISMATCH')
        g=finite_scope(spec,current['graphs']);p=record.get('result',{}).get('result',{})
        check=parser_check(kernel(),record['input']['name'],g,p,record['id'])
        current['materials'][spec['material_id']].setdefault('tool_evidence',[]).append({'receipt_id':record['id'],
             'operation':'resolve','graph_id':g['id'],'query':record['input']['name'],'status':p.get('status'),
             'binding_check':check['status'],'binding_receipt_id':spec['_receipt_id']})
        atomic(job/'current.json',current)
        return {'status':check['status'],'existing_receipt_id':record['id'],'check':check,'parser_calls':0}
    if op=='upsert':
        current['foundation_contract']=FOUNDATION
        for key in ['title','overview','relations','source_facts','source_conflicts','unknowns','product_structure_policy','relation_policy']:
            if key in spec:current[key]=deepcopy(spec[key])
        for item in spec.get('materials',[]):
            if set(item)&{'review','kernel_passport','kernel_naming','kernel_rule_naming','kernel_inputs','naming_verification','iupac_assessment'}:raise ValueError('DERIVED_CHECK_FIELDS_NOT_EDITABLE')
            mid=item['id']
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',mid):raise ValueError('MATERIAL_ID_INVALID')
            ensure_refs(item.get('source_refs',current['materials'].get(mid,{}).get('source_refs')),index)
            merged={**current['materials'].get(mid,{}),**deepcopy(item)}
            merged['independent_review']='NOT_REVIEWED';merged['preferred_iupac_name']=None
            if merged.get('most_likely_name'):merged['most_likely_name']['certified_preferred_iupac']=False
            old=current['materials'].get(mid)
            if old and material_hash(old,current['graphs'],current)!=material_hash(merged,current['graphs'],current):
                current['withdrawals'].append({'kind':'material_revision','id':mid,'previous':old,'reason':spec.get('change_reason','Primary-session revision'),'time':now()})
            current['materials'][mid]=merged
        for mid in spec.get('withdraw_material_ids',[]):
            old=current['materials'].pop(mid,None)
            if old:current['withdrawals'].append({'kind':'material_withdrawal','id':mid,'previous':old,'reason':spec.get('change_reason'),'time':now()})
        atomic(job/'current.json',current)
        from .adoption import enabled
        projected=compact(current['materials'])
        if enabled(current):
            projected={x['id']:{k:current['materials'][x['id']].get(k) for k in ('id','label','kind','most_likely_name')}
                       for x in spec.get('materials',[])}
        return {'materials':projected,'material_state_sha256':{i:material_hash(m,current['graphs'],current) for i,m in current['materials'].items()},'errors':validate(current,index,expected_reference_policy=run.get('material_reference_policy'))}
    if op=='review':
        k=kernel();results=[]
        for entry_index, entry in enumerate(spec.get('materials',[])):
            mid=entry['id']
            try:
                m=current['materials'][mid];h=material_hash(m,current['graphs'],current)
                if entry.get('state_sha256')!=h:raise ValueError('REVIEW_STALE_STATE:'+mid)
                if not entry.get('reason'):raise ValueError('REVIEW_REASON_REQUIRED')
                saved=parser_for_review(m,job,current);before=h;h=material_hash(m,current['graphs'],current)
                from .evidence import receipts_for
                context={**current,'tool_receipts':receipts_for(job,current.get('tool_receipts',{}))}
                result=review_material(k,m,context,saved)
                m.update({key:value for key,value in result.items() if key!='input_sha256'})
                m['review']={'contract':FOUNDATION,'state_sha256':h,'requested_state_sha256':before,'kernel_input_sha256':result['input_sha256'],'reason':entry['reason'],'reviewer':entry.get('reviewer','SAME_PRIMARY_SESSION'),'time':now(),'independent_review':'NOT_REVIEWED'}
                # Each completed object survives a later failure or interruption.
                # Report it as checkpointed only after the write succeeds.
                atomic(job/'current.json',current)
                results.append({'id':mid,'state_sha256':h,'kernel_status':result['kernel_passport'].get('status'),'name_check':result['naming_verification']['status'],'preferred_iupac_name':None})
            except Exception as exc:
                attach(exc, stage='review', material_id=mid, entry_index=entry_index, path=f'materials[{entry_index}]', checkpointed_material_ids=[x['id'] for x in results])
                raise
        atomic(job/'current.json',current);return {'reviewed':results,'errors':validate(current,index,expected_reference_policy=run.get('material_reference_policy'))}
    if op=='finalize':
        from .adoption import enabled
        if not enabled(current):raise ValueError('EXPLICIT_NEW_ADOPTION_POLICY_REQUIRED')
        if not spec.get('reason'):raise ValueError('FINAL_MODEL_REVIEW_REASON_REQUIRED')
        from .source_review import required, bind
        if required(current):
            refs={b['id'] for b in index.get('blocks',[])}|{'page:'+str(n) for n in range(1,index.get('page_count',0)+1)}|{'text:input'}
            current['source_review']=bind(current,spec.get('source_checks'),refs)
            atomic(job/'current.json',current)
        entries=[{'id':mid,'state_sha256':material_hash(m,current['graphs'],current),
                  'reason':spec.get('material_reasons',{}).get(mid) or spec['reason']}
                 for mid,m in current['materials'].items() if m.get('major')]
        reviewed=execute('review',{'materials':entries},job)
        finished=execute('finish',{},job)
        return {**finished,'review_receipt_id':reviewed['receipt_id']}
    if op=='finish':
        errors=validate(current,index,expected_reference_policy=run.get('material_reference_policy'));result={'status':'READY_FOR_HOST_COMMIT' if not errors else 'INCOMPLETE','errors':errors,'candidate_sha256':digest(current),'time':now()}
        atomic(job/'completion.json',result);return result
    raise ValueError('UNKNOWN_OPERATION')

def execute(op,spec,job):
    """Every actual operation gets one immutable receipt, including failures."""
    job=Path(job).resolve();started=now();rid=uuid.uuid4().hex
    try:
        result=_execute(op,{**spec,'_receipt_id':rid},job);code=0
    except Exception as exc:
        atomic(job/'tool-events'/(rid+'.json'),{'id':rid,'operation':op,'input':spec,'input_sha256':digest(spec),
               'result':failure_result(exc),'started_at':started,'finished_at':now(),'exit_code':1})
        raise
    atomic(job/'tool-events'/(rid+'.json'),{'id':rid,'operation':op,'input':spec,'input_sha256':digest(spec),
           'result':result,'started_at':started,'finished_at':now(),'exit_code':code})
    return {**result,'receipt_id':rid}

def main():
    p=argparse.ArgumentParser();p.add_argument('operation');p.add_argument('--input');p.add_argument('--output');p.add_argument('--job',default='.')
    args=p.parse_args();job=Path(args.job).resolve();spec=read(args.input,{}) if args.input else {};started=now()
    try:result=execute(args.operation,spec,job);exit_code=0
    except Exception as e:result=failure_result(e);exit_code=1
    if args.output:
        out=Path(args.output).resolve()
        if not out.is_relative_to(job):raise ValueError('TOOL_OUTPUT_MUST_BE_IN_JOB')
        atomic(out,result)
    print(json.dumps(result,ensure_ascii=False));raise SystemExit(exit_code)
if __name__=='__main__':main()

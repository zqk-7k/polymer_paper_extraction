from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, os, uuid, time
APP = Path(__file__).resolve().parents[1]

def fs_path(p):
    p=Path(p)
    if os.name=='nt' and not str(p).startswith('\\\\?\\'):
        raw=os.path.abspath(p)
        if len(raw)>=240:return Path('\\\\?\\UNC\\'+raw[2:] if raw.startswith('\\\\') else '\\\\?\\'+raw)
    return p
def digest(v): return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def file_hash(p): return hashlib.sha256(fs_path(p).read_bytes()).hexdigest()
def now(): return datetime.now(timezone.utc).isoformat()
def read(p,default=None):
    p=fs_path(p)
    # utf-8-sig: identical to utf-8 for BOM-less files, and tolerant of model-written
    # files whose PowerShell redirection carried a UTF-8 BOM (observed in preflight).
    return json.loads(p.read_text(encoding='utf-8-sig')) if p.exists() else default
def atomic(p,v):
    p=fs_path(p);p.parent.mkdir(parents=True,exist_ok=True)
    # Keep temporary basenames short even for hash-named caches on Windows.
    tmp=p.parent/('.tmp-'+uuid.uuid4().hex+'.json')
    with tmp.open('w',encoding='utf-8') as f:
        json.dump(v,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
    try:
        for attempt,delay in enumerate((0.03,0.08,0.15,0.3,0)):
            try:os.replace(tmp,p);break
            except PermissionError as error:
                if getattr(error,'winerror',None) not in (5,32,33) or attempt==4:raise
                time.sleep(delay)
    finally:
        if tmp.exists():tmp.unlink()
def config(): return read(APP/'config/runtime.json')
def data_root(): return Path(os.environ.get('IDENTITY_APP_DATA',config()['data_root'])).resolve()
def material_hash(m,graphs,context=None):
    from .adoption import enabled, context as adoption_context
    if context and enabled(context):
        return digest(adoption_context(m,{**context,'graphs':graphs}))
    derived=('review','kernel_passport','kernel_naming','kernel_rule_naming','kernel_inputs','naming_verification','iupac_assessment')
    body={'material':{k:v for k,v in m.items() if k not in derived},'graphs':[graphs[g] for g in m.get('graph_ids',[]) if g in graphs]}
    if context and context.get('foundation_contract'):
        body['context']={k:context.get(k) for k in ('foundation_contract','relations','source_facts','unknowns')}
        if 'product_structure_policy' in context:body['context']['product_structure_policy']=context['product_structure_policy']
        if 'relation_policy' in context:body['context']['relation_policy']=context['relation_policy']
        if m.get('nomenclature_declaration'):
            visited={m['id']};dependencies={}
            def visit(item):
                d=item.get('nomenclature_declaration') or {}
                ids=[d.get('base_material_id'),*[x.get('material_id') for x in d.get('monomers',[])],
                     *[x.get('material_id') for x in d.get('graft_sources',[])],
                     *[x.get('source_material_id') for x in d.get('substituents',[])],
                     *[x.get('material_id') for x in item.get('components',[]) if x.get('relation')=='physical_blend_component']]
                ids += [x.get('material_id') for x in (d.get('source_declaration') or {}).get('monomers',[])]
                if d.get('contract') in ('identity-model-nomenclature/1.0','identity-model-nomenclature/1.1'):
                    source=(d.get('proposal') or {}).get('source_declaration') or {}
                    ids += [x.get('material_id') for x in item.get('components',[])]
                    ids += [source.get('base_material_id'),source.get('branch_material_id'),*[x.get('material_id') for x in source.get('monomers',[])],
                            *[x.get('material_id') for x in source.get('graft_sources',[])]]
                for mid in ids:
                    other=context.get('materials',{}).get(mid)
                    if not other or mid in visited:continue
                    visited.add(mid);dependencies[mid]={'material':{k:v for k,v in other.items() if k not in derived},
                        'graphs':[graphs[g] for g in other.get('graph_ids',[]) if g in graphs]}
                    visit(other)
            visit(m);body['context']['nomenclature_dependencies']=dependencies
    return digest(body)
def validate(candidate,index,expected_reference_policy=None):
    errors=[];materials=candidate.get('materials',{});graphs=candidate.get('graphs',{})
    from .material_references import errors as reference_errors
    errors.extend(reference_errors(candidate,expected_reference_policy))
    from .source_review import errors as source_review_errors
    errors.extend(source_review_errors(candidate,index))
    major=[m for m in materials.values() if m.get('major') is True]
    if not major:errors.append('MAIN_MATERIALS_MISSING')
    if not candidate.get('title') or not candidate.get('overview'):errors.append('TITLE_OR_OVERVIEW_MISSING')
    refs={b['id'] for b in index.get('blocks',[])}|{'page:'+str(i) for i in range(1,index.get('page_count',0)+1)}|{'text:input'}
    for m in materials.values():
        from .adoption import enabled
        if enabled(candidate):
            from .properties import property_errors
            errors.extend(x+':'+m['id'] for x in property_errors(m,refs,candidate))
        if not m.get('label') or not m.get('kind'):errors.append('MATERIAL_LABEL_KIND_MISSING:'+m['id'])
        for r in m.get('source_refs',[]):
            if r not in refs:errors.append('SOURCE_REF_INVALID:'+r)
        if m.get('major'):
            if not (m.get('most_likely_name') or {}).get('text'):errors.append('MAIN_NAME_MISSING:'+m['id'])
            if not m.get('graph_ids'):errors.append('MAIN_ENCODED_SCOPE_MISSING:'+m['id'])
            if not m.get('source_refs'):errors.append('MAIN_SOURCE_MISSING:'+m['id'])
            review=m.get('review') or {}
            context=candidate if review.get('contract') else None
            if review.get('state_sha256')!=material_hash(m,graphs,context):errors.append('CURRENT_GRAPH_NAME_REVIEW_REQUIRED:'+m['id'])
        if (m.get('naming_verification') or {}).get('status')=='MISMATCH':errors.append('NAME_GRAPH_MISMATCH:'+m['id'])
        assessment=m.get('iupac_assessment') or {}
        if assessment.get('formal_name') and not assessment.get('primary_matches_display'):
            errors.append('DECLARED_NOMENCLATURE_NAME_MISMATCH:'+m['id'])
        if candidate.get('foundation_contract') and m.get('major') and not m.get('naming_verification'):errors.append('NAME_SCOPE_CHECK_REQUIRED:'+m['id'])
        if candidate.get('naming_policy')=='iupac-name-required/1.0' and m.get('major'):
            if (m.get('most_likely_name') or {}).get('basis')=='material_expression':errors.append('IUPAC_NAME_REQUIRED_NOT_DESCRIPTION:'+m['id'])
            if (m.get('naming_verification') or {}).get('status') not in ('GRAPH_MATCH','SOURCE_SCOPE_MATCH'):
                errors.append('IUPAC_DECLARED_SCOPE_CHECK_REQUIRED:'+m['id'])
        if candidate.get('naming_policy')=='iupac-model-assisted/1.1':
            from .source_conflicts import conflict_errors
            errors.extend(x+':'+m['id'] for x in conflict_errors(m,candidate,refs))
        if candidate.get('naming_policy') in ('iupac-model-assisted/1.0','iupac-model-assisted/1.1') and m.get('major'):
            if (m.get('most_likely_name') or {}).get('basis')=='material_expression':errors.append('IUPAC_NAME_REQUIRED_NOT_DESCRIPTION:'+m['id'])
            finite=all(graphs.get(g,{}).get('scope')=='finite_molecule' for g in m.get('graph_ids',[]))
            from .chemistry_checks import source_only_oligomer
            if source_only_oligomer(m,candidate):
                # Finite source graphs do not declare one finite oligomer product.
                finite=False
            if finite and m.get('kind') in ('component','monomer','oligomer'):
                if (m.get('naming_verification') or {}).get('status')!='GRAPH_MATCH':errors.append('FINITE_NAME_GRAPH_CHECK_REQUIRED:'+m['id'])
            elif assessment.get('contract')!=('identity-model-nomenclature/1.1' if candidate.get('naming_policy')=='iupac-model-assisted/1.1' else 'identity-model-nomenclature/1.0') or not assessment.get('formal_name') or (m.get('naming_verification') or {}).get('status')!='MODEL_RULE_REVIEWED':
                errors.append('CURRENT_MODEL_NAMING_REVIEW_REQUIRED:'+m['id'])
        if candidate.get('product_structure_policy')=='product-structure-expression/1.0' and m.get('major') and m.get('kind') in ('polymer','prepolymer','oligomer','network','blend'):
            from .constitution import expression_errors
            errors.extend(x+':'+m['id'] for x in expression_errors(m,candidate))
        for g in m.get('graph_ids',[]):
            if g not in graphs:errors.append('GRAPH_NOT_RECEIVED:'+g)
        name=m.get('most_likely_name') or {}
        if name.get('certified_preferred_iupac') or m.get('independently_reviewed'):errors.append('SELF_CERTIFICATION_FORBIDDEN:'+m['id'])
        if name and (not name.get('basis') or not name.get('scope') or not name.get('reason')):errors.append('NAME_BASIS_SCOPE_REASON_REQUIRED:'+m['id'])
    if index.get('page_count') and not candidate.get('observations'):errors.append('SOURCE_IMAGES_NOT_OBSERVED')
    from .relations import relation_errors
    errors.extend(relation_errors(candidate,refs))
    return errors
def publish(job):
    job=Path(job);candidate=read(job/'current.json',{});index=read(job/'source-index.json',{})
    state=read(job/'run.json',{})
    errors=validate(candidate,index,expected_reference_policy=state.get('material_reference_policy'))
    if errors:return {'status':'INCOMPLETE','errors':errors}
    state=read(job/'run.json');root=data_root();body={'contract':'identity-single-core/1.0','kernel_version':'0.9.0','job_id':job.name,'source_sha256':state['source_sha256'],'candidate':candidate,'source_index':index,'independent_review':'NOT_REVIEWED','preferred_iupac_certification':False}
    from .evidence import receipts_for
    body['tool_evidence']=receipts_for(job)
    body['foundation_contract']=candidate.get('foundation_contract')
    version=digest(body);bundle={**body,'version':version};dest=root/'versions'/version/'bundle.json'
    if dest.exists():
        if read(dest)!=bundle:raise ValueError('IMMUTABLE_VERSION_CONFLICT')
    else:atomic(dest,bundle)
    # Bundle is complete before source and job adoption pointers are atomically replaced.
    pointer={'job_id':job.name,'version':version,'source_sha256':state['source_sha256'],'adopted_at':now()}
    atomic(root/'adopted'/(state['source_sha256'].replace(':','_')+'.json'),pointer)
    atomic(job/'adopted.json',pointer)
    recovered=read(dest)
    if digest({k:v for k,v in recovered.items() if k!='version'})!=version:raise ValueError('BUNDLE_READBACK_HASH_MISMATCH')
    return {'status':'DELIVERED','version':version,'readback':'PASS','major_material_count':sum(m.get('major') is True for m in candidate['materials'].values())}

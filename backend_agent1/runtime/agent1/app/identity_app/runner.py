import argparse, json, os, shutil, subprocess, sys, time, uuid
from pathlib import Path
from .storage import APP, config, data_root, atomic, read, now, digest, file_hash, publish, validate
from .source import prepare

def task_id(): return 'SC-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'-'+uuid.uuid4().hex[:8]

def implementation_snapshot():
    files={str(p.relative_to(APP)).replace('\\','/'):file_hash(p) for area in ['identity_app','resources','polymer','config','data','third_party'] for p in (APP/area).rglob('*') if p.is_file() and not any(x in p.parts for x in ['__pycache__','build'])}
    cfg=config()
    for item in cfg.get('runtime_files',{}).values():
        if not Path(item['path']).is_file() or file_hash(item['path'])!=item['sha256']:
            raise ValueError('CLI_RUNTIME_FILE_MISSING_OR_CHANGED: '+Path(item['path']).name)
    return {'files':files,'sha256':digest(files),'runtime':cfg}

def require_preflight():
    receipt=read(data_root()/'preflight.json',{})
    if receipt.get('status')!='PASS':raise ValueError('CLI_PREFLIGHT_REQUIRED')
    if receipt.get('implementation_sha256')!=implementation_snapshot()['sha256']:
        raise ValueError('CLI_PREFLIGHT_IMPLEMENTATION_CHANGED')
    if time.time()-receipt.get('verified_epoch',0)>12*3600:
        raise ValueError('CLI_PREFLIGHT_EXPIRED')
    return receipt

def init_job(pdf=None,text=None,minutes=60,job_id=None):
    root=data_root();job=root/'jobs'/(job_id or task_id());job.mkdir(parents=True,exist_ok=False)
    if pdf:
        shutil.copy2(pdf,job/'source.pdf');source_sha=file_hash(job/'source.pdf');kind='pdf'
    else:
        (job/'input.txt').write_text(text,encoding='utf-8');source_sha=file_hash(job/'input.txt');kind='text'
    from .adoption import CURRENT_POLICY as POLICY
    from .material_references import CONTRACT as REFERENCE_POLICY
    state={'job_id':job.name,'contract':'identity-single-core/1.0','adoption_policy':POLICY,'status':'PREPARING_SOURCE','input_kind':kind,'source_sha256':source_sha,'started_at':now(),'started_epoch':time.time(),'deadline_epoch':time.time()+minutes*60,'budget_seconds':minutes*60,'closeout_reserve_seconds':900,'human_interventions':[],'first_run_unattended':None,'independent_review':'NOT_REVIEWED','model':'gpt-6.1-sol','reasoning_effort':'xhigh','sandbox_requested':'workspace-write','calls':[]}
    state['material_reference_policy']=REFERENCE_POLICY
    atomic(job/'run.json',state)
    wrapper="import sys\nfrom pathlib import Path\nsys.path.insert(0,"+repr(str(APP))+ ")\nfrom identity_app.tools import main\nif __name__ == '__main__': main()\n"
    (job/'run_tool.py').write_text(wrapper,encoding='utf-8')
    prompt=(APP/'resources/core-prompt.md').read_text(encoding='utf-8').replace('PYTHON_EXECUTABLE',config()['python'])
    if kind=='text':prompt+='\n\n'+(APP/'resources/text-input.md').read_text(encoding='utf-8')
    (job/'AGENTS.md').write_text(prompt,encoding='utf-8')
    shutil.copy2(APP/'resources/naming-guide.md',job/'naming-guide.md')
    shutil.copy2(APP/'resources/polymer-identity/references/solve.md',job/'skill-method.md')
    atomic(job/'current.json',{'foundation_contract':'identity-foundation/1.1','adoption_policy':POLICY,'material_reference_policy':REFERENCE_POLICY,'naming_policy':'iupac-model-assisted/1.1','relation_policy':'identity-relations/1.0','product_structure_policy':'product-structure-expression/1.0','materials':{},'graphs':{},'observations':[],'withdrawals':[]})
    atomic(job/'implementation.json',{**implementation_snapshot(),'prompt_sha256':file_hash(job/'AGENTS.md'),
                                    'skill_method_sha256':file_hash(job/'skill-method.md')})
    return job
def session_from(folder):
    sid=None;usage=[];tools=[]
    for path in sorted(Path(folder).glob('call-*/stdout.jsonl')):
        for line in path.read_text(encoding='utf-8',errors='replace').splitlines():
            try:e=json.loads(line)
            except ValueError:continue
            if e.get('type')=='thread.started':sid=e.get('thread_id')
            if e.get('type')=='turn.completed':usage.append(e.get('usage'))
            if e.get('type')=='item.completed':tools.append(e.get('item',{}).get('type'))
    return sid,usage,tools
def stop_owned(proc):
    if proc.poll() is None:
        if os.name=='nt':subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True)
        else:proc.terminate()
        try:proc.wait(timeout=10)
        except subprocess.TimeoutExpired:proc.kill()
def rollout_evidence(session):
    """CLI JSONL omits some code-mode image calls; inspect only this session rollout."""
    root=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))/'sessions'
    paths=list(root.glob('*/*/*/*'+str(session)+'.jsonl')) if session else []
    contexts=[];images=[];calls=0
    for p in paths:
        for line in p.read_text(encoding='utf-8',errors='replace').splitlines():
            try:e=json.loads(line)
            except ValueError:continue
            v=e.get('payload',{})
            if e.get('type')=='turn_context':contexts.append({k:v.get(k) for k in ['cwd','model','effort','approval_policy','sandbox_policy']})
            if e.get('type')=='response_item' and v.get('type') in ('function_call','custom_tool_call'):
                calls+=1;args=str(v.get('arguments') or v.get('input') or '')
                if 'view_image' in args:images.append({'tool':v.get('name'),'call_id':v.get('call_id'),'arguments':args})
    return {'rollout_paths':[str(p) for p in paths],'rollout_sha256':[file_hash(p) for p in paths],'effective_contexts':contexts,'image_tool_calls':images,'function_call_count':calls,'provider_model_request_count':'NOT_EXPOSED'}
def invoke(job,prompt,until,session=None):
    state=read(job/'run.json');count=len(state['calls'])+1;folder=job/('call-'+str(count).zfill(2));folder.mkdir(exist_ok=False)
    (folder/'prompt.txt').write_text(prompt,encoding='utf-8')
    cfg=config();command=[cfg['cli'],'exec']
    if session:command+=['resume',session]
    command+=['--json','--ignore-user-config','--skip-git-repo-check','-m',cfg['model'],'-c','model_reasoning_effort="xhigh"','-c','sandbox_mode="workspace-write"','-c','approval_policy="never"','-c','windows.sandbox="unelevated"','-c','sandbox_workspace_write.network_access=true','-o',str(folder/'answer.txt')]
    if not session:command+=['--sandbox','workspace-write','-C',str(job)]
    # Dual-mode transport switch: when IDENTITY_RELAY_CODEX_CONFIG is set, append the
    # JSON list of '-c' provider-routing overrides (API-relay mode; ready-made lists in
    # Data/private/relay-overrides-*.json); unset means the normal machine-login account
    # mode. Routing only — chemistry/tools unchanged; overrides land verbatim in
    # command.json, and the API key travels via the provider env_key variable.
    relay_overrides=os.environ.get('IDENTITY_RELAY_CODEX_CONFIG')
    if relay_overrides:command+=json.loads(relay_overrides)
    command+=['-'];atomic(folder/'command.json',command)
    # Keep system authentication/runtime, but do not inherit parent chat identifiers.
    env={**os.environ,'PYTHONPATH':str(APP),'PYTHONIOENCODING':'utf-8','PYTHONUTF8':'1',
         'OPSIN_JAR':str(APP/'third_party/opsin-core.jar'),
         'OPSIN_BUILD_DIR':str(job/'tool-runtime'/'opsin-build')}
    for key in ['CODEX_THREAD_ID','CODEX_SESSION_ID']:env.pop(key,None)
    atomic(folder/'environment-references.json',{'PYTHONPATH':str(APP),'OPSIN_JAR':env['OPSIN_JAR'],
        'OPSIN_BUILD_DIR':env['OPSIN_BUILD_DIR'],'credential_values_recorded':False,'requested_sandbox':'workspace-write','parent_permission_profile':os.environ.get('CODEX_PERMISSION_PROFILE'),'runtime_directory':str(Path(cfg['cli']).parent)})
    started=time.time();timed_out=False;cancelled=False
    with (folder/'stdout.jsonl').open('wb') as out,(folder/'stderr.txt').open('wb') as err:
        proc=subprocess.Popen(command,cwd=job,stdin=subprocess.PIPE,stdout=out,stderr=err,env=env,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        atomic(folder/'process.json',{'pid':proc.pid,'started_at':now(),'command_sha256':digest(command)})
        proc.stdin.write(prompt.encode('utf-8'));proc.stdin.close()
        while proc.poll() is None:
            if (job/'stop-request.json').exists():cancelled=True;stop_owned(proc);break
            if time.time()>=until:timed_out=True;stop_owned(proc);break
            time.sleep(1)
    sid,usage,tool_types=session_from(job)
    runtime=rollout_evidence(sid or session);atomic(folder/'verified-runtime.json',runtime)
    receipt={'call':count,'session_id':sid or session,'exit_code':proc.returncode,'timed_out':timed_out,'cancelled':cancelled,'elapsed_seconds':time.time()-started,'usage':usage[-1] if usage else None,'observed_item_types':sorted(set(t for t in tool_types if t)),'command':command,'model_verification':'REQUESTED_CLI_MODEL; provider response model not exposed','sandbox_requested':'workspace-write','actual_permission_verification':'SEE_RAW_CLI_AND_TOOL_EVENTS'}
    for line in (folder/'stdout.jsonl').read_text(encoding='utf-8',errors='replace').splitlines():
        try:event=json.loads(line)
        except ValueError:continue
        if event.get('type') in ('error','turn.failed'):
            message=str(event.get('message') or event.get('error') or '')
            if 'capacity' in message.lower():
                receipt['failure_kind']='MODEL_CAPACITY';receipt['runtime_error']=message[:500]
    atomic(folder/'receipt.json',receipt);state=read(job/'run.json');state['calls'].append(receipt);state['session_id']=sid or session;atomic(job/'run.json',state);return receipt

def ready_commit(job):
    """Finish an already model-reviewed valid candidate; never supply chemistry."""
    from .adoption import enabled
    candidate=read(job/'current.json',{});state=read(job/'run.json',{})
    if not enabled(candidate) or state.get('adoption_policy')!=candidate['adoption_policy']:
        return None
    if (job/'sealed.json').exists() or time.time()>=state.get('deadline_epoch',0):
        return None
    if validate(candidate,read(job/'source-index.json',{}),expected_reference_policy=state.get('material_reference_policy')):
        return None
    from .tools import execute
    completion=execute('finish',{},job)
    if completion['status']!='READY_FOR_HOST_COMMIT':return None
    return publish(job)


def run_job(job):
    job=Path(job).resolve();state=read(job/'run.json')
    if state['contract']!='identity-single-core/1.0':raise ValueError('ONLY_NEW_EXPLICIT_JOB_ALLOWED')
    if state.get('status')=='DELIVERED':return state
    if (job/'sealed.json').exists():raise ValueError('SEALED_JOB_IMMUTABLE_NEW_JOB_REQUIRED')
    if time.time()>=state['deadline_epoch']:raise ValueError('ORIGINAL_JOB_DEADLINE_EXPIRED')
    if (job/'stop-request.json').exists():return state
    require_preflight()
    if read(job/'implementation.json')['sha256']!=implementation_snapshot()['sha256']:
        raise ValueError('JOB_IMPLEMENTATION_CHANGED')
    if not (job/'source-index.json').exists():prepare(job)
    state=read(job/'run.json');state['status']='UNDERSTANDING_AND_BUILDING';atomic(job/'run.json',state)
    deadline=state['deadline_epoch'];session=state.get('session_id')
    initial=('请完成用户文本描述的高分子化学身份证与最可能IUPAC名称。先读AGENTS.md末尾文本适配、input.txt和source-index.json；只有text:input来源，无PDF或图页。调用run_tool.py完成建图、命名、review/finalize及finish。' if state.get('input_kind')=='text' else '请完成本篇完整化学身份证。先读取AGENTS.md、全文和来源索引，自主读图、调用run_tool.py、保存、review并finish。')
    prompt=('继续本任务已保存状态与同一session，不重置预算。' if session else initial)+' 总截止epoch='+str(deadline)+'；最后15分钟收尾。只访问本任务来源，不访问其他论文/参考或历史结果。'
    first=invoke(job,prompt,max(time.time()+1,deadline-900),session)
    session=first['session_id'];seen=set();result=None
    for recovery in range(3):
        if first.get('cancelled'):break
        auto=ready_commit(job)
        if auto and auto.get('status')=='DELIVERED':result=auto;break
        completion=read(job/'completion.json',{})
        if completion.get('status')=='READY_FOR_HOST_COMMIT':
            # Zero-model host save/adoption recovery, never rebuild scientific answers.
            for local in range(3):
                try:result=publish(job);break
                except (OSError,ValueError) as e:atomic(job/('commit-error-'+str(local)+'.json'),{'error':str(e),'time':now()});time.sleep(1)
            if result and result.get('status')=='DELIVERED':break
        errors=validate(read(job/'current.json'),read(job/'source-index.json'))
        signature=digest({'candidate':read(job/'current.json'),'errors':errors})
        from .adoption import enabled
        capacity=enabled(read(job/'current.json')) and first.get('failure_kind')=='MODEL_CAPACITY'
        if (signature in seen and not capacity) or not session or time.time()>=deadline-30 or recovery>=2:break
        seen.add(signature)
        if capacity:
            delay=(30,60)[recovery]
            if time.time()+delay>=deadline-30:break
            atomic(job/('capacity-backoff-'+str(recovery+1)+'.json'),{'time':now(),'delay_seconds':delay,
                'session_id':session,'deadline_epoch':deadline,'reason':'actualMODEL_CAPACITY; bounded same-session retry'})
            time.sleep(delay)
        follow='在原session、原截止时间内收尾。读取snapshot现有产物，只修复具体错误；不要重读重建整篇。错误：'+json.dumps(errors,ensure_ascii=False)+ '。新1.5回看影响身份/量的原页，finalize带当前source_checks、observations、identity_limits及conflict_ids覆盖主要对象identity/quantities；详见AGENTS.md；旧合同仍review/finish。剩余秒数='+str(max(0,int(deadline-time.time())))
        first=invoke(job,follow,deadline-15,session)
    state=read(job/'run.json');state.update(finished_at=now(),elapsed_seconds=time.time()-state['started_epoch'],delivery=result or {'status':'INCOMPLETE','errors':validate(read(job/'current.json'),read(job/'source-index.json'))})
    state['status']='STOPPED' if first.get('cancelled') else state['delivery']['status']
    if state['status']=='INCOMPLETE' and first.get('failure_kind'):state['failure_kind']=first['failure_kind']
    state['first_run_unattended']=state['status']=='DELIVERED' and not state['human_interventions']
    state['first_run_scientific_accuracy']='NOT_INDEPENDENTLY_REVIEWED'
    atomic(job/'run.json',state);atomic(job/'sealed.json',{'job_id':job.name,'sealed_at':now(),'run_sha256':file_hash(job/'run.json'),'candidate_sha256':file_hash(job/'current.json'),'completion_sha256':file_hash(job/'completion.json') if (job/'completion.json').exists() else None,'reference_not_solver_input':True})
    from .capability_feedback import record
    feedback_root=(job.parent.parent if job.parent.name=='jobs' else job.parent)/'capability-feedback'
    try:record(job,root=feedback_root)
    except (ValueError,OSError,KeyError,TypeError) as exc:
        # Delivery is already sealed; surface feedback failure outside that job.
        atomic(feedback_root/job.name/'feedback-error.json',{'time':now(),'error':str(exc),'sealed_job_unchanged':True})
    return state

def preflight():
    from PIL import Image,ImageDraw
    job=init_job(text='Engineering preflight: marker CORE-READ-17. Neutral finite tool probe: 2-fluoroethan-1-ol. No paper or manual chemical reference.',minutes=30,job_id='PREFLIGHT-'+uuid.uuid4().hex[:8])
    prepare(job);pic=Image.new('RGB',(500,200),'white');ImageDraw.Draw(pic).text((30,60),'VISUAL CHECK 7',fill='black',font_size=35);pic.save(job/'visual.png')
    atomic(job/'graph-request.json',{'id':'preflight-g','smiles':'[*:1]CC[*:2]','scope':'repeat_unit','source_refs':['text:input']})
    atomic(job/'opsin-request.json',{'name':'2-fluoroethan-1-ol','scope':'finite_molecule'})
    python=config()['python']
    prompt=f"This is a small engineering preflight, no paper. Read input.txt, use view_image to read visual.png and report the visual marker. Execute both exact domain commands: & '{python}' .\\run_tool.py check_structure --input .\\graph-request.json --output .\\graph-response.json ; & '{python}' .\\run_tool.py resolve --input .\\opsin-request.json --output .\\opsin-response.json . Read both real outputs. Then write checkpoint.json with input marker, actual visual marker, returned formula and actual OPSIN status. Do not change tool/source files or compile outside this job. Reply briefly."
    call=invoke(job,prompt,time.time()+420)
    checkpoint=read(job/'checkpoint.json',{});g=read(job/'graph-response.json',{});sid=call['session_id']
    opsin=read(job/'opsin-response.json',{})
    from .chemistry_checks import compare_graphs
    from .tools import kernel
    parsed=opsin.get('result',{})
    finite_check=compare_graphs(kernel(),'OCCF',parsed.get('isomeric_smiles') or parsed.get('candidate_smiles'),'finite_molecule') if parsed.get('status')=='PARSED' else {'status':'UNSUPPORTED','reason_code':parsed.get('reason_code','OPERATION_NOT_EXECUTED')}
    local_build=job/'tool-runtime'/'opsin-build'/'OpsinBridge.class'
    if call['exit_code']!=0 or not checkpoint or not g.get('graph') or not sid:
        result={'status':'FAILED','job':str(job),'reason':'REAL_FILE_IMAGE_TOOL_WRITE_OR_SESSION_FAILED','receipt':call}
    else:
        resume=invoke(job,'Resume verification only: read your previously saved checkpoint.json; write resume-checkpoint.json containing same visual marker and your current session id if known. No paper work. Reply marker.',time.time()+240,sid)
        resumed=read(job/'resume-checkpoint.json')
        runtime=rollout_evidence(sid);viewed=bool(runtime['image_tool_calls']);effective=all(c.get('sandbox_policy',{}).get('type')=='workspace-write' and c.get('model')=='gpt-6.1-sol' and c.get('effort')=='xhigh' for c in runtime['effective_contexts']) and bool(runtime['effective_contexts'])
        opsin_ok=(finite_check['status']=='GRAPH_MATCH' and opsin.get('parser_calls')==1 and parsed.get('source',{}).get('type')=='OPSIN' and local_build.is_file())
        result={'status':'PASS' if resumed and resume['exit_code']==0 and viewed and effective and opsin_ok else 'FAILED','job':str(job),'session_id':sid,'same_session_resumed':resume['session_id']==sid,'graph_formula':g['graph']['formula'],'graph_depiction':bool(g['graph'].get('depiction')),'actual_view_image_event':viewed,'effective_runtime_verified':effective,'file_write_executed':bool(checkpoint),'resume_write_executed':bool(resumed),'actual_local_opsin':opsin_ok,'finite_name_graph_check':finite_check,'opsin_build_directory':str(local_build.parent),'requested_sandbox':'workspace-write','kernel':'0.9.0','independent_review':'NOT_REVIEWED'}
    frozen=read(job/'implementation.json');current=implementation_snapshot()
    if current['sha256']!=frozen['sha256']:result.update(status='FAILED',reason='IMPLEMENTATION_CHANGED_DURING_PREFLIGHT')
    result.update(implementation_sha256=frozen['sha256'],verified_epoch=time.time())
    atomic(data_root()/'preflight.json',result);print(json.dumps(result,ensure_ascii=False));return result
def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['run','resume','preflight']);p.add_argument('--pdf');p.add_argument('--text');p.add_argument('--job');p.add_argument('--minutes',type=float,default=60);a=p.parse_args()
    if a.action=='preflight':result=preflight()
    else:
        require_preflight()
        job=Path(a.job) if a.action=='resume' else init_job(a.pdf,a.text,a.minutes);print(str(job),flush=True);result=run_job(job);print(json.dumps(result,ensure_ascii=False))
    raise SystemExit(0 if result.get('status') in ('PASS','DELIVERED') else 2)
if __name__=='__main__':main()

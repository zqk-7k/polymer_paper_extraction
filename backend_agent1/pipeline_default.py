"""Default routing only. Extraction remains in the verified PDF runner."""
from pathlib import Path
from datetime import datetime
import argparse
import json
import subprocess
import sys
import uuid
import agent1_pdf_runner as bridge

ROOT=Path(__file__).resolve().parent

def main(argv=None):
    p=argparse.ArgumentParser(description='默认：原始PDF → agent1 → 已有下游 → 原值导出')
    p.add_argument('--input-dir',type=Path)
    select=p.add_mutually_exclusive_group()
    select.add_argument('--ref-no',action='append')
    select.add_argument('--ref-list',type=Path)
    select.add_argument('--max-documents',type=int)
    p.add_argument('--output-dir',type=Path)
    p.add_argument('--entry-config',type=Path,default=ROOT/'config/agent1_entry.json')
    p.add_argument('--workers',type=int,choices=range(1,5))
    p.add_argument('--resume',action='store_true')
    p.add_argument('--status',action='store_true')
    p.add_argument('--dry-run',action='store_true')
    a=p.parse_args(argv)
    if a.resume or a.status:
        if not a.output_dir: p.error('恢复或查询必须提供 --output-dir')
        if a.input_dir or a.ref_no or a.ref_list or a.max_documents or a.workers:
            p.error('恢复只使用已冻结输入和并发配置；不可附带新的输入参数')
        out=a.output_dir.resolve()
        if not (out/'pdf_contract.json').is_file():p.error('输出目录没有可恢复的任务')
        c=bridge.read(out/'pdf_contract.json');bridge.verify_contract(c)
        if a.status:
            print(json.dumps(bridge.status(out),ensure_ascii=False,indent=2));return 0
    else:
        if not a.input_dir:p.error('新任务必须提供 --input-dir')
        from pipeline_runner import select_pdfs
        pdfs=select_pdfs(a.input_dir.resolve(),ref_nos=a.ref_no,ref_list_path=a.ref_list,max_documents=a.max_documents)
        if not pdfs:p.error('未选中文献')
        entry_config = a.entry_config.resolve()
        settings=bridge.read(entry_config)
        if not settings:p.error('正式入口配置不存在')
        config_root = entry_config.parent
        def configured_path(key):
            value = Path(settings[key]).expanduser()
            return value if value.is_absolute() else (config_root / value).resolve()
        out=(a.output_dir or configured_path('output_root')/(datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6])).resolve()
        if out.exists() and any(out.iterdir()):p.error('输出目录已存在；恢复请使用 --resume，禁止覆盖')
        if a.dry_run:
            print(json.dumps({'workflow':'agent1','pdfs':[str(x) for x in pdfs],'output':str(out),'model_calls':0},ensure_ascii=False));return 0
        args=argparse.Namespace(output=out,pdf=pdfs,agent1_app=configured_path('agent1_app'),
            java_home=configured_path('java_home'),mineru_env=configured_path('mineru_env'),
            config=configured_path('downstream_config'),minutes=settings['minutes'],workers=a.workers or settings['workers'])
        c=bridge.prepare(args)
        for f in (Path(__file__).resolve(),a.entry_config.resolve()):c['frozen_files'][str(f)]=bridge.sha(f)
        bridge.write(out/'pdf_contract.json',c)
    if a.dry_run:
        print(json.dumps({'resume':str(out),'model_calls':0}));return 0
    if bridge.status(out)['completed']:
        print('任务已完成，已核对导出；不重复调用模型。');return 0
    print('任务目录：'+str(out),flush=True)
    env=bridge.environment(c)
    # Original preflight validity includes implementation hash and expiration.
    check=subprocess.run([c['agent1_python'],'-B','-c','from identity_app.runner import require_preflight; require_preflight()'],
        cwd=c['agent1_app'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    if check.returncode:
        bridge.checked_call([sys.executable,'-B','-X','utf8',ROOT/'agent1_pdf_runner.py','preflight','--output',out],out/'entry.log',env)
    return subprocess.run([sys.executable,'-B','-X','utf8',ROOT/'agent1_pdf_runner.py',
                           'resume' if a.resume else 'run','--output',out],env=env).returncode

if __name__=='__main__':raise SystemExit(main())

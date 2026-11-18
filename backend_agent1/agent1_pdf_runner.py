"""PDF -> native agent1 job -> existing downstream. Explicit inputs, bounded recovery."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'extraction'))
from agent1_workflow.run_lifecycle import Lease, BusyError, active


def read(path, default=None):
    path = Path(path)
    return json.loads(path.read_text('utf-8-sig')) if path.exists() else default


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.writing')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), 'utf8'); tmp.replace(path)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def environment(contract):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
               IDENTITY_APP_DATA=contract['identity_store'])
    # A standalone CLI must not attach to the desktop parent's registered Core.
    # The original runner still explicitly enforces workspace-write / never.
    for key in ('CODEX_WINDOWS_REGISTERED_CORE', 'CODEX_WINDOWS_SANDBOX_PACKAGE_FAMILY',
                'CODEX_APP_TOOLS_PIPE_PATH', 'CODEX_APP_RUNTIME_CLI_PATH'):
        env.pop(key, None)
    # The source parser and the original agent1 parser accept different key spellings.
    # Normalize the environment only; credentials never enter a manifest or a command.
    for key in ('MinerU_KEY', 'MINERU_API_KEY', 'MINERU_KEY'):
        env.pop(key, None)
    for line in Path(contract['mineru_env']).read_text('utf-8-sig').splitlines():
        line = line.strip().removeprefix('export ')
        if '=' not in line or line.startswith('#'): continue
        key, value = line.split('=', 1)
        if key.strip() in ('MinerU_KEY', 'MINERU_API_KEY', 'MINERU_KEY'):
            env['MINERU_API_KEY'] = value.strip().strip('\"\'')
    if not env.get('MINERU_API_KEY'):
        raise ValueError('Selected MinerU env file has no nonempty supported key')
    env['PATH'] = str(Path(contract['java_home']) / 'bin') + os.pathsep + env.get('PATH', '')
    env['JAVA_HOME'] = contract['java_home']
    return env


def checked_call(command, log, env, cwd=ROOT):
    log = Path(log); log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('a', encoding='utf8') as f:
        result = subprocess.run([str(x) for x in command], cwd=cwd, env=env,
                                stdout=f, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError('Child stage failed (exit %s); see %s' % (result.returncode, log.name))


def verify_contract(contract):
    for filename, expected in contract['frozen_files'].items():
        if not Path(filename).is_file() or sha(filename) != expected:
            raise ValueError('Frozen source/code/config changed: ' + filename)


def prepare(args):
    out = args.output.resolve()
    if (out / 'pdf_contract.json').exists():
        raise ValueError('Use resume for an existing PDF run')
    if out.exists() and any(out.iterdir()):
        raise ValueError('A new PDF run requires an empty output directory')
    app = args.agent1_app.resolve(); config = read(app / 'config/runtime.json')
    required = [Path(config['python']), Path(config['cli']), args.config, args.mineru_env,
                args.java_home / 'bin/java.exe', args.java_home / 'bin/javac.exe']
    if not all(p.is_file() for p in required):
        raise ValueError('Agent1 runtime, Java, MinerU env or downstream config is missing')
    papers = {}
    for pdf in args.pdf:
        pdf = pdf.resolve()
        if not pdf.is_file() or not re.fullmatch(r'reference_no_\d+', pdf.stem):
            raise ValueError('Each input must be a reference_no_NUMBER.pdf file')
        if pdf.stem in papers: raise ValueError('Duplicate reference number')
        papers[pdf.stem] = {'original_pdf': str(pdf), 'sha256': sha(pdf)}
    out.mkdir(parents=True)
    for paper, item in papers.items():
        copied = out / 'sources' / (paper + '.pdf'); copied.parent.mkdir(exist_ok=True)
        shutil.copy2(item['original_pdf'], copied); item['pdf'] = str(copied)
    frozen = [Path(__file__).resolve(), ROOT / 'extraction/agent1_workflow/native_bundle.py',
              app / 'config/runtime.json', args.config.resolve(), ROOT / 'pipeline_runner.py']
    frozen += [Path(item['pdf']) for item in papers.values()]
    contract = {'schema': 'agent1.pdf_end_to_end.v1', 'papers': papers, 'agent1_app': str(app),
                'agent1_python': config['python'], 'downstream_python': sys.executable,
                'java_home': str(args.java_home.resolve()), 'mineru_env': str(args.mineru_env.resolve()),
                'downstream_config': str(args.config.resolve()), 'identity_store': str(out / 'identity_store'),
                'minutes': args.minutes, 'frozen_files': {str(p): sha(p) for p in frozen},
                'quality_review': False, 'format_conversion': False, 'AB': False,
                'identity_concurrency': 1, 'workers': args.workers}
    write(out / 'pdf_contract.json', contract)
    return contract


def identity(out, paper):
    contract = read(out / 'pdf_contract.json'); verify_contract(contract)
    sys.path.insert(0, contract['agent1_app'])
    from identity_app.runner import init_job, run_job, require_preflight
    require_preflight()
    folder = out / 'papers' / paper
    pointer = read(folder / 'identity_job.json')
    if pointer:
        job = Path(pointer['job'])
    else:
        job = init_job(pdf=contract['papers'][paper]['pdf'], minutes=contract['minutes'])
        write(folder / 'identity_job.json', {'job': str(job), 'source_sha256': contract['papers'][paper]['sha256']})
    result = run_job(job)
    if result.get('status') != 'DELIVERED':
        raise RuntimeError('Agent1 did not deliver: ' + str(result.get('status')))


def execute_paper(out, paper):
    contract = read(out / 'pdf_contract.json'); verify_contract(contract)
    folder = out / 'papers' / paper; env = environment(contract)
    lease = Lease(folder / 'paper.lock').acquire()
    def phase(name):
        event = {'paper': paper, 'phase': name, 'status': 'running', 'updated_epoch': time.time()}
        write(folder / 'state.json', event)
        with (folder / 'phase_events.jsonl').open('a', encoding='utf8') as stream:
            stream.write(json.dumps(event) + '\n')
    try:
        from agent1_workflow.api import prepare as downstream_prepare, execute as downstream_execute, status as downstream_status
        downstream = folder / 'downstream'
        if (downstream / 'production_contract.json').exists():
            phase('downstream_resume')
            result = downstream_execute(downstream, workers=1)
            if not result['completed']: raise RuntimeError('Downstream remains incomplete')
        else:
            document = folder / 'source/documents' / (paper + '_document.json')
            if not (folder / 'source_receipt.json').exists():
                phase('source_parse')
                command = [contract['downstream_python'], '-B', '-X', 'utf8', ROOT / 'pipeline_runner.py',
                           '--workflow', 'source-only', '--input-dir', out / 'sources', '--ref-no', paper,
                           '--mineru-output', folder / 'mineru', '--organized-root', folder / 'organized',
                           '--processed-output', folder / 'source', '--config', contract['downstream_config'],
                           '--env-file', contract['mineru_env'], '--skip-meta', '--skip-extraction']
                # An interrupted remote OCR batch is resumed, never resubmitted blindly.
                manifests = list((folder / 'mineru').glob('batch_*_manifest.json'))
                if len(manifests) > 1: raise ValueError('Multiple OCR batches require explicit selection')
                if manifests:
                    command += ['--batch-id', manifests[0].stem.removeprefix('batch_').removesuffix('_manifest')]
                checked_call(command, folder / 'source.log', env)
                write(folder / 'source_receipt.json', {'pdf_sha256': sha(contract['papers'][paper]['pdf']),
                      'document': str(document), 'document_sha256': sha(document), 'fresh_source_parse': True,
                      'metadata_model_skipped': True})
            receipt = read(folder / 'source_receipt.json')
            if receipt['pdf_sha256'] != sha(contract['papers'][paper]['pdf']) or receipt['document_sha256'] != sha(document):
                raise ValueError('Prepared original source changed')
            phase('waiting_agent1')
            identity_lock = Lease(out / 'identity_execution.lock')
            while True:
                try: identity_lock.acquire(); break
                except BusyError: time.sleep(1)
            try:
                phase('agent1')
                checked_call([contract['agent1_python'], '-B', '-X', 'utf8', Path(__file__).resolve(),
                              '_identity', '--output', out, '--paper', paper], folder / 'agent1.log', env)
            finally: identity_lock.release()
            phase('handoff')
            job = read(folder / 'identity_job.json')['job']
            checked_call([contract['downstream_python'], '-B', '-X', 'utf8',
                          ROOT / 'extraction/agent1_workflow/native_bundle.py', '--job', job,
                          '--store', contract['identity_store'], '--pdf', contract['papers'][paper]['pdf'],
                          '--document', document, '--agent1-app', contract['agent1_app'], '--output', folder / 'bundles'],
                         folder / 'handoff.log', env)
            phase('downstream')
            downstream_prepare([document], folder / 'bundles', downstream, Path(contract['downstream_config']))
            result = downstream_execute(downstream, workers=1)
            if not result['completed']: raise RuntimeError('Downstream remains incomplete')
        if not downstream_status(downstream)['completed']: raise RuntimeError('Export is incomplete')
        verify_contract(contract)
        write(folder / 'state.json', {'paper': paper, 'phase': 'export', 'status': 'completed', 'updated_epoch': time.time()})
        return 0
    except Exception as exc:
        previous = read(folder / 'state.json', {})
        write(folder / 'state.json', {**previous, 'status': 'failed', 'error_type': type(exc).__name__,
                                     'error': str(exc), 'updated_epoch': time.time()})
        raise
    finally: lease.release()


def status(out):
    contract = read(out / 'pdf_contract.json')
    rows = []
    for paper in contract['papers']:
        folder = out / 'papers' / paper
        state = read(folder / 'state.json', {'paper': paper, 'status': 'pending'})
        if active(folder / 'paper.lock'): state['status'] = 'running'
        elif state['status'] == 'running': state['status'] = 'interrupted'
        if state['status'] == 'completed':
            from agent1_workflow.api import status as downstream_status
            if not downstream_status(folder / 'downstream')['completed']: state['status'] = 'delivery_incomplete'
        rows.append(state)
    return {'papers': rows, 'completed': all(p['status'] == 'completed' for p in rows)}


def main():
    parser = argparse.ArgumentParser(description='原始PDF → agent1真实执行 → 原值导出')
    sub = parser.add_subparsers(dest='action', required=True)
    prepare_parser = sub.add_parser('prepare')
    prepare_parser.add_argument('--pdf', nargs='+', type=Path, required=True)
    for name in ('agent1-app', 'java-home', 'mineru-env', 'config'):
        prepare_parser.add_argument('--' + name, type=Path, required=True)
    prepare_parser.add_argument('--minutes', type=float, default=60)
    prepare_parser.add_argument('--workers', type=int, default=3, choices=range(1,5))
    for name in ('run', 'resume', 'status', 'preflight', '_paper', '_identity'):
        p = sub.add_parser(name)
        if name in ('run', 'resume'): p.add_argument('--select', nargs='+')
        if name in ('_paper', '_identity'): p.add_argument('--paper', required=True)
    for p in sub.choices.values(): p.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); out = args.output.resolve()
    if args.action == 'prepare': prepare(args); print('Prepared original-PDF workflow'); return 0
    if args.action == 'status': print(json.dumps(status(out), ensure_ascii=False, indent=2)); return 0
    if args.action == '_identity': identity(out, args.paper); return 0
    if args.action == '_paper': return execute_paper(out, args.paper)
    contract = read(out / 'pdf_contract.json'); verify_contract(contract); env = environment(contract)
    if args.action == 'preflight':
        checked_call([contract['agent1_python'], '-B', '-X', 'utf8', '-m', 'identity_app.runner', 'preflight'],
                     out / 'preflight.log', env, Path(contract['agent1_app']))
        print('Agent1 real preflight passed'); return 0
    selected = args.select or list(contract['papers'])
    if set(selected) - set(contract['papers']): raise ValueError('Unknown paper selection')
    root_lease = Lease(out / 'dispatcher.lock').acquire()
    try:
        if any(active(out / 'papers' / p / 'paper.lock') for p in selected):
            raise BusyError('A selected paper is still running')
        def run(paper):
            try:
                checked_call([contract['downstream_python'], '-B', '-X', 'utf8', Path(__file__).resolve(),
                              '_paper', '--output', out, '--paper', paper], out / 'papers' / paper / 'runner.log', env)
                return {'paper': paper, 'exit_code': 0}
            except RuntimeError: return {'paper': paper, 'exit_code': 1}
        with ThreadPoolExecutor(max_workers=contract['workers']) as pool:
            results = [f.result() for f in as_completed([pool.submit(run,p) for p in selected])]
        write(out / 'last_execution.json', {'selected':selected, 'results':results})
        print(json.dumps(status(out), ensure_ascii=False, indent=2))
        return 0 if all(x['exit_code'] == 0 for x in results) else 1
    finally: root_lease.release()


if __name__ == '__main__':
    raise SystemExit(main())

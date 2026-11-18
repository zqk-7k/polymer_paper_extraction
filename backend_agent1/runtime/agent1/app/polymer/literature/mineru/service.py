"""Resumable MinerU v4 batches; reference: https://mineru.net/apiManage/docs."""
from __future__ import annotations
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import requests
from dotenv import load_dotenv
from .corpus import normalize_archive, sha256, validate_document

BASE = 'https://mineru.net/api/v4'


def safe_error(exc) -> str:
    text = re.sub(r'https?://[^\s]+', '[url]', str(exc))
    for name in ('MinerU_KEY', 'MINERU_API_KEY', 'MINERU_KEY', 'ARK_API_KEY', 'DMX_API_KEY'):
        secret = os.environ.get(name, '')
        if secret:
            text = text.replace(secret, '[redacted]')
    return f'{type(exc).__name__}: {text[:500]}'


class MinerUClient:
    def __init__(self, env_file: Path, *, request=None):
        load_dotenv(env_file, override=False, encoding='utf-8-sig')
        keys = ('MinerU_KEY', 'MINERU_API_KEY', 'MINERU_KEY')
        self.token = next((os.environ[k].strip() for k in keys if os.environ.get(k, '').strip()), '')
        if not self.token:
            raise ValueError('Missing MinerU_KEY in project .env')
        self.transport = request or requests.request

    def request(self, method, url, *, auth=False, tries=4, **kwargs):
        headers = {'Authorization': 'Bearer ' + self.token} if auth else {}
        for attempt in range(tries):
            try:
                if hasattr(kwargs.get('data'), 'seek'):
                    kwargs['data'].seek(0)
                response = self.transport(method, url, headers=headers, timeout=(30, 180), **kwargs)
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt + 1 < tries:
                        delay = response.headers.get('Retry-After', '')
                        response.close()
                        time.sleep(min(120, float(delay)) if delay.isdigit() else min(30, 2**attempt))
                        continue
                if not 200 <= response.status_code < 300:
                    code = response.status_code
                    response.close()
                    raise RuntimeError(f'MinerU HTTP {code}')
                return response
            except (requests.Timeout, requests.ConnectionError):
                if attempt + 1 == tries:
                    raise RuntimeError('MinerU network error; resume from saved state') from None
                time.sleep(min(30, 2**attempt))
        raise RuntimeError('Request retry budget exhausted')

    def api(self, method, path, **kwargs):
        response = self.request(method, BASE + path, auth=True,
            tries=1 if method == 'POST' else 4, **kwargs)
        try:
            value = response.json()
        finally:
            response.close()
        if value.get('code') != 0:
            raise RuntimeError(f"MinerU API code={value.get('code')}: {value.get('msg', '')}")
        return value.get('data') or {}

    def submit(self, docs, options):
        data = self.api('POST', '/file-urls/batch', json={**options, 'files': [
            {'name': d['doc_id'] + '.pdf', 'data_id': d['doc_id']} for d in docs]})
        if not data.get('batch_id') or len(data.get('file_urls', [])) != len(docs):
            raise RuntimeError('MinerU returned invalid batch/upload mapping')
        return data['batch_id'], data['file_urls']

    def upload(self, doc, url):
        path = Path(doc['source_paths'][0])
        if sha256(path) != doc['sha256']:
            raise ValueError('PDF changed since inventory')
        with path.open('rb') as stream:
            self.request('PUT', url, data=stream).close()

    def download(self, url, path):
        part = path.with_suffix('.zip.part')
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.request('GET', url, stream=True) as response, part.open('wb') as out:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    out.write(chunk)
        part.replace(path)

def poll_batch(client, docs, manifest, save, args):
    batch_id = docs[0]['parse']['batch_id']
    active = {d['doc_id']: d for d in docs}
    deadline = time.monotonic() + args.wait_minutes * 60
    while active:
        data = client.api('GET', '/extract-results/batch/' + batch_id)
        for result in data.get('extract_result') or []:
            doc_id = result.get('data_id') or str(result.get('file_name', '')).removesuffix('.pdf')
            doc = active.get(doc_id)
            if doc is None:
                continue
            state = doc['parse']
            state['remote_state'] = result.get('state')
            if result.get('state') == 'failed':
                state.update(status='failed', error=safe_error(result.get('err_msg', 'Remote parse failed')))
                active.pop(doc_id)
            elif result.get('state') == 'done':
                try:
                    archive = Path(manifest['work_dir']) / 'archives' / f'{doc_id}.zip'
                    if not result.get('full_zip_url'):
                        raise ValueError('Missing result download URL')
                    client.download(result['full_zip_url'], archive)
                    verified = normalize_archive(archive, Path(manifest['output_dir']), doc,
                        manifest['options_hash'], batch_id)
                    state.update(status='done', **verified)
                    state.pop('error', None)
                except Exception as exc:
                    state.update(status='download_failed', error=safe_error(exc))
                active.pop(doc_id)
            elif result.get('state') == 'waiting-file' and not state.get('uploaded'):
                state.update(status='upload_failed', error='Upload interrupted; use --retry-failed')
                active.pop(doc_id)
        save()
        print(f'MinerU batch {batch_id}: remaining={len(active)}', flush=True)
        if not active:
            return
        if time.monotonic() >= deadline:
            print('Poll deadline reached; existing batch IDs retained for next run', flush=True)
            return
        time.sleep(args.poll_interval)


def run_parse(client, docs, manifest, save, args):
    resumable = {}
    for doc in docs:
        state = doc.setdefault('parse', {'status': 'pending'})
        if doc.get('preflight_error'):
            state.update(status='rejected', error=doc['preflight_error'])
            continue
        if state['status'] == 'done':
            try:
                validate_document(Path(manifest['output_dir']) / doc['doc_id'], doc['doc_id'],
                    source_sha=doc['sha256'], options_hash=manifest['options_hash'])
                continue
            except Exception:
                state['status'] = 'download_failed'
        if state['status'] == 'submitting':
            state.update(status='submit_unknown', error='Interrupted submission; use --retry-failed explicitly')
        if args.retry_failed and state['status'] in {'failed', 'upload_failed', 'submit_unknown'}:
            doc.setdefault('parse_history', []).append(dict(state))
            state.clear(); state['status'] = 'pending'
        if state.get('batch_id') and state['status'] in {'processing', 'uploading', 'download_failed'}:
            resumable.setdefault(state['batch_id'], []).append(doc)
    save()
    for group in resumable.values():
        poll_batch(client, group, manifest, save, args)
    pending = [d for d in docs if d['parse']['status'] == 'pending']
    for offset in range(0, len(pending), args.batch_size):
        group = pending[offset:offset + args.batch_size]
        for doc in group:
            doc['parse'] = {'status': 'submitting'}
        save()
        try:
            batch_id, urls = client.submit(group, manifest['options'])
        except Exception as exc:
            for doc in group:
                doc['parse'].update(status='submit_unknown', error=safe_error(exc))
            save()
            raise
        for doc in group:
            doc['parse'].update(status='uploading', batch_id=batch_id, uploaded=False)
        save()
        with ThreadPoolExecutor(max_workers=args.upload_workers) as pool:
            futures = {pool.submit(client.upload, d, url): d for d, url in zip(group, urls)}
            for future in as_completed(futures):
                doc = futures[future]
                try:
                    future.result()
                    doc['parse'].update(status='processing', uploaded=True)
                except Exception as exc:
                    doc['parse'].update(status='upload_failed', error=safe_error(exc))
                save()
        # Poll even after an uncertain upload error: the server may have accepted it.
        poll_batch(client, group, manifest, save, args)
    save()

"""Resume a generic source -> packet -> model -> citation check -> export workflow."""
import argparse
from dataclasses import asdict, replace
import hashlib
import json
import time
from pathlib import Path

from llm_client import DEFAULT_CONFIG_PATH, LLMClient, load_pipeline_config, resolve_llm_config, resolve_pricing_config
from stages.sample_catalog import digest
from stages.source_model_extraction import SYSTEM_PROMPT, work_packets, split_packet, source_fingerprint, attach_bundle
from tools.source_extraction_export import build_source_export


def workflow_rule_hashes():
    root=Path(__file__).resolve().parents[1]
    names=('stages/source_model_extraction.py','stages/source_article_extraction.py','stages/source_table_extraction.py',
           'stages/source_table_layout.py','stages/source_text_extraction.py',
           'stages/source_field_enrichment.py','stages/source_figure_links.py','stages/source_semantic_normalization.py',
           'tools/source_extraction_export.py','tools/run_source_workflow.py')
    return {name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in names}


def write(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    temp.replace(path)


def run(source_root, output_root, model='deepseek-v4.1-flash', documents=None,
        max_requests=None, resume=False, max_chars=3500, client_factory=None, input_kind='source',
        replay_from=None, offline=False, max_consecutive_failures=3, retry_review=False, config_path=None,
        asset_roots=(), context_mode='article_once'):
    source_root, output_root = Path(source_root).resolve(), Path(output_root).resolve()
    if source_root == output_root or source_root in output_root.parents or output_root in source_root.parents:
        raise ValueError('Output must be separate from source')
    if max_requests is not None and max_requests < 0:
        raise ValueError('Invalid request limit')
    if max_consecutive_failures < 1:
        raise ValueError('Invalid failure limit')
    if offline:
        max_requests=0
    if input_kind not in {'source','stage0'}:
        raise ValueError('Unknown source input kind')
    filename = 'source_extraction.json' if input_kind=='source' else 'stage0_blocks.json'
    paths = sorted(source_root.glob('reference_no_*/'+filename))
    if documents:
        paths = [p for p in paths if p.parent.name in documents]
        if set(documents) != {p.parent.name for p in paths}:
            raise ValueError('Requested source document missing')
    if not paths:
        raise ValueError('No source extraction documents; rebuild source inventory first')
    snapshots = {str(p):p.read_bytes() for p in paths}
    code = Path(__file__).resolve().parents[1]
    import yaml
    schema = yaml.safe_load((code/'config/polymer_schema.yaml').read_text(encoding='utf-8'))
    target_ids = [s+':'+k for s in ('property_vocabulary','stage5_property_vocabulary','specialized_property_vocabulary') for k in schema[s]]
    config_file = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    config = load_pipeline_config(config_file)
    output_tokens = int(config.get('stages',{}).get('stage4_property',{}).get('max_tokens') or 32768)
    if output_tokens < 1:
        raise ValueError('Invalid output token limit')
    article_once = context_mode == 'article_once'
    from stages.source_article_extraction import ARTICLE_PROMPT
    prompt = ARTICLE_PROMPT if article_once else SYSTEM_PROMPT
    if article_once:
        retry_review = False
    options = {'max_chars':max_chars, 'context_chars':16000, 'context_mode':context_mode}
    if article_once:
        from stages.source_article_extraction import build_property_catalog
        registry=json.loads((code/'config/standard_property_codes.v1.json').read_text(encoding='utf8'))
        options['property_catalog']=build_property_catalog(schema,registry)
    contract = {'source_hashes':{p:hashlib.sha256(v).hexdigest() for p,v in snapshots.items()},
                'target_ids':target_ids, 'model':model, 'packet_options':options, 'input_kind':input_kind,
                'prompt_sha256':digest(prompt), 'max_tokens':output_tokens,
                'llm_config_sha256':hashlib.sha256(config_file.read_bytes()).hexdigest(),
                'asset_roots':[str(Path(p).resolve()) for p in asset_roots],
                'rules':workflow_rule_hashes()}
    if resume:
        if json.loads((output_root/'contract.json').read_text(encoding='utf-8')) != contract:
            raise ValueError('Resume contract differs; use a new output directory')
    else:
        output_root.mkdir(parents=True, exist_ok=False)
        write(output_root/'contract.json', contract)
    if replay_from:
        replay_from=Path(replay_from).resolve()
        prior=json.loads((replay_from/'contract.json').read_text(encoding='utf-8'))
        if any(prior.get(k)!=contract[k] for k in ('source_hashes','model','target_ids','input_kind')):
            raise ValueError('Replay sources, model or target catalog differ')
    if client_factory is None and not offline and max_requests!=0:
        resolved = replace(resolve_llm_config(config,'stage4_property'), model=model, requested_model=model,
                           max_retries=0)
        pricing = resolve_pricing_config(config, model) if model in config.get('pricing',{}).get('models',{}) else None
        client_factory = lambda: LLMClient(resolved, pricing=pricing)
    output_sources = output_root/'sources'
    output_sources.mkdir(exist_ok=True)
    requests, results, consecutive_failures, circuit_open = 0, [], 0, False
    for path in paths:
        data = json.loads(snapshots[str(path)])
        if input_kind=='stage0':
            from stages.source_table_extraction import build_source_extraction
            data=build_source_extraction(data, include_local_reviews=False)
        if asset_roots:
            data['source_asset_roots']=contract['asset_roots']
        if data['document_id'] != path.parent.name:
            raise ValueError('Source document identity mismatch')
        directory = output_sources/data['document_id']
        directory.mkdir(exist_ok=True)
        bundle_path = directory/'model_text_bundle.json'
        bundle = (json.loads(bundle_path.read_text(encoding='utf-8')) if bundle_path.exists() else
                  {'schema_version':'source_model_text.v1', 'source_fingerprint':source_fingerprint(data),
                   'packet_options':options, 'target_ids':target_ids, 'requested_model':model, 'responses':{}})
        packets = work_packets(data, bundle)
        if replay_from:
            saved_bundle=replay_from/'sources'/data['document_id']/'model_text_bundle.json'
            if saved_bundle.is_file():
                saved=json.loads(saved_bundle.read_text(encoding='utf-8'))
                if saved.get('source_fingerprint')==bundle['source_fingerprint']:
                    current_ids={p['packet_id'] for p in packets}
                    bundle['responses'].update({k:v for k,v in saved.get('responses',{}).items() if k in current_ids})
            by_range={(p['focal_block_id'],p['focal_start'],p['focal_end']):p for p in packets}
            for response_path in sorted((replay_from/'calls'/data['document_id']).glob('*/response.json')):
                request=json.loads((response_path.parent/'request.json').read_text(encoding='utf-8'))
                old_packet=json.loads(request['user_message'])['packet']
                packet=by_range.get((old_packet['focal_block_id'],old_packet['focal_start'],old_packet['focal_end']))
                if packet is None or packet['packet_id'] in bundle['responses']:
                    continue
                from stages.source_model_extraction import validate_response
                response=json.loads(response_path.read_text(encoding='utf-8'))
                if validate_response(data,old_packet,response,target_ids)[2]:
                    bundle['responses'][packet['packet_id']]={'request_packet_sha256':digest(old_packet),
                        'original_request_packet':old_packet,'response':response,
                        'replayed_response_path':str(response_path)}
        calls_root = output_root/'calls'/data['document_id']
        calls_root.mkdir(parents=True, exist_ok=True)
        review_attempted=set()
        while packets:
            packet=packets.pop(0)
            pid = packet['packet_id']
            previous=None
            if pid in bundle['responses']:
                from stages.source_model_extraction import validate_response
                record=bundle['responses'][pid]
                old_rows,old_issues,_=validate_response(data,record.get('original_request_packet',packet),record['response'],target_ids)
                repairable=[i for i in old_issues if i.get('reason') in {
                    'invalid_response_schema','missing_source_citation','source_quote_missing_or_ambiguous',
                    'citation_outside_request','value_outside_focal_range','malformed_observation','invalid_condition_name'}]
                if not retry_review or not repairable or pid in review_attempted:
                    continue
                previous={'previous_response':record['response'],'validation_errors':repairable,
                          'instruction':'Repair the source citations using only this packet. Every property/value/material/unit/condition evidence must be a citation object, never a string. Do not normalize source notation. Return the complete corrected observations and explicitly unresolved items.'}
                review_attempted.add(pid)
            if circuit_open or (max_requests is not None and requests >= max_requests):
                break
            # A resume never silently reissues a failed or incomplete article request.
            # A deliberate new run directory is needed for a fresh attempt.
            if article_once and any(calls_root.glob(pid+'_attempt_*')):
                continue
            attempt = len(list(calls_root.glob(pid+'_attempt_*'))) + 1
            call_dir = calls_root/(pid+'_attempt_'+str(attempt))
            call_dir.mkdir()
            request = {'system_prompt':prompt,
                       'user_message':json.dumps({'target_ids':target_ids, 'packet':packet,
                                                 **(previous or {})},ensure_ascii=False),
                       'max_tokens':contract['max_tokens']}
            write(call_dir/'request.json',request)
            client = client_factory()
            requests += 1
            status = {'packet_id':pid, 'status':'running'}
            resolved = getattr(client, 'resolved', None)
            if resolved is not None:
                status['request_settings'] = {k:getattr(resolved,k) for k in
                    ('model','timeout_seconds','thinking_effort','api_format','stream')}
            write(call_dir/'status.json',status)
            print(json.dumps({'document_id':data['document_id'], **status}), flush=True)
            started = time.monotonic()
            try:
                response = client.call_json(**request).data
                write(call_dir/'response.json',response)
                from stages.source_model_extraction import validate_response
                rows, issues, complete = validate_response(data,packet,response,target_ids)
                if complete and previous:
                    # A malformed neighbor must not erase an already usable result
                    # if the repair model omits it from its corrected response.
                    new_ids={r['observation_id'] for r in rows}
                    retained=[]
                    for item in previous['previous_response'].get('observations',[]):
                        good,_,_=validate_response(data,record.get('original_request_packet',packet),
                            {'observations':[item],'unresolved':[],'has_more':False},target_ids)
                        if good and good[0]['observation_id'] not in new_ids:
                            retained.append(item)
                    response={**response,'observations':response['observations']+retained}
                    rows,issues,complete=validate_response(data,packet,response,target_ids)
                # Incomplete and malformed responses are retained in attempts, not cached
                # as completed work. Successful empty results are valid and resumable.
                if complete or article_once:
                    bundle['responses'][pid] = {'request_packet_sha256':digest(packet), 'response':response}
                    if previous:
                        bundle['responses'][pid]['repair_history']={'original_response':previous['previous_response'],
                            'validation_errors':previous['validation_errors'],'repair_request_path':str(call_dir/'request.json')}
                    write(bundle_path,bundle)
                    if retry_review and not previous and issues:
                        packets.insert(0,packet)
                elif isinstance(response,dict) and response.get('has_more') is True and split_packet(packet):
                    bundle.setdefault('split_packet_ids',[]).append(pid)
                    write(bundle_path,bundle)
                    packets=split_packet(packet)+packets
                status.update(status='completed' if complete else 'needs_retry',
                              published_candidates=len(rows), issues=issues)
                consecutive_failures=0 if complete else consecutive_failures+1
            except Exception as exc:
                status.update(status='failed', error_type=type(exc).__name__)
                consecutive_failures+=1
                if type(exc).__name__=='LLMOutputTruncatedError' and split_packet(packet):
                    bundle.setdefault('split_packet_ids',[]).append(pid)
                    write(bundle_path,bundle)
                    packets=split_packet(packet)+packets
                    status['status']='split_for_retry'
            if consecutive_failures>=max_consecutive_failures:
                circuit_open=True
            status['elapsed_seconds'] = round(time.monotonic()-started,3)
            raw = getattr(client,'last_raw_response',None)
            if raw is not None:
                write(call_dir/'raw_response.json',asdict(raw))
                status.update(actual_model=raw.model, finish_reason=raw.finish_reason,
                              usage=asdict(raw.usage),
                              cost=asdict(raw.cost) if raw.cost else None)
            write(call_dir/'status.json',status)
            print(json.dumps({'document_id':data['document_id'],'packet_id':pid,'status':status['status']}), flush=True)
        write(bundle_path,bundle)
        result = attach_bundle(data,bundle)
        write(directory/'source_extraction.json',result)
        results.append({'document_id':data['document_id'], 'counts':result['counts'],
                        'model_text_coverage':result['model_text_coverage']})
    unchanged = all(Path(p).read_bytes()==v for p,v in snapshots.items())
    if not unchanged:
        raise ValueError('Source changed during extraction')
    revision = len(list(output_root.glob('export_*'))) + 1
    export_dir = output_root/f'export_{revision:03d}'
    manifest = build_source_export(output_sources,export_dir)
    from tools.audit_target_property_coverage import audit
    audit_dir = output_root/f'audit_{revision:03d}'
    audit(output_sources,export_dir,audit_dir,scope_status='draft')
    pending = sum(len(r['model_text_coverage']['pending_packet_ids']) for r in results)
    summary = {'schema_version':'source_workflow.v1','requested_model':model, 'documents':results,
               'api_requests_this_run':requests, 'pending_packets':pending,
               'offline':offline,'stopped_after_consecutive_failures':circuit_open,
               'status':'text_scan_finished' if not pending else 'incomplete',
               'goal_complete':False,'original_inputs_unchanged':True,
               'export_dir':str(export_dir), 'audit_dir':str(audit_dir), 'export_counts':manifest['counts'],
               'extraction_mode':context_mode,
               'validation_mode':'basic' if article_once else 'exact_citations',
               'limitations':['Basic validation retains model output; source location is best-effort, not semantic verification.' if article_once else 'Model citations prove source location, not independent semantic correctness.',
                              'Text scan completion does not certify recall. Figures require locations and links only; image value extraction is outside scope.']}
    write(output_root/'summary.json',summary)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source-root','output-root'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--model',default='deepseek-v4.1-flash')
    parser.add_argument('--documents',nargs='+')
    parser.add_argument('--max-requests',type=int)
    parser.add_argument('--max-chars',type=int,default=3500)
    parser.add_argument('--context-mode',choices=('article_once','local','full_article'),default='article_once',
                        help='默认每篇全文单次抽取并做基础校验；另两种为历史逐段模式')
    parser.add_argument('--input-kind',choices=('source','stage0'),default='source')
    parser.add_argument('--replay-from',type=Path)
    parser.add_argument('--offline',action='store_true')
    parser.add_argument('--max-consecutive-failures',type=int,default=3)
    parser.add_argument('--retry-review',action='store_true')
    parser.add_argument('--config-path',type=Path)
    parser.add_argument('--asset-roots',type=Path,nargs='+',default=[])
    parser.add_argument('--resume',action='store_true')
    result=run(**vars(parser.parse_args()))
    print(json.dumps({k:v for k,v in result.items() if k!='documents'},ensure_ascii=True,default=str))

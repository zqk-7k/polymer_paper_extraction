"""Audited fresh calls. Retries keep identical inputs; successful tasks resume locally."""
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
import time
from requests.exceptions import RequestException
from common import *
from llm_client import LLMClient, LLMJSONResponse,resolve_pricing_config

class AttemptsExhaustedError(RuntimeError):
    """Current invocation's final cause, independent of previous attempt files."""
    def __init__(self, errors):
        self.attempt_error_types=tuple(errors)
        self.last_error_type=errors[-1] if errors else None
        super().__init__('Frozen unchanged-attempt policy exhausted: '+','.join(errors))

def workflow_hashes():
    return [sha(OUT/'frozen_manifest.json')]


def event(dest, row):
    dest.mkdir(parents=True, exist_ok=True)
    with (dest / 'calls.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')


def request(dest, task_id, stage, system, packet, max_tokens, *, native=False, require_complete=True):
    settings = config()
    fallback_tokens=settings.get('stage_output_truncation_fallback_tokens',{}).get(stage,settings['output_truncation_fallback_tokens'])
    if require_complete:
        from response_completion import GUIDANCE
        system += GUIDANCE
        if stage == 'stage4t_table_interpretation':
            from subject_scope import GUIDANCE as SCOPE_GUIDANCE
            system += SCOPE_GUIDANCE
    message = packet if isinstance(packet, str) else json.dumps(packet, ensure_ascii=False, separators=(',', ':'))
    input_size = len(system.encode('utf-8')) + len(message.encode('utf-8'))
    budget = settings['native_identity_input_utf8_bytes'] if native else settings['group_input_utf8_bytes']
    if input_size > budget:
        write(dest / 'blocked' / (task_id + '.json'), {'reason': 'input_budget_exceeded_no_truncation',
            'input_bytes': input_size, 'budget': budget, 'stage': stage})
        raise ValueError('Complete request exceeds frozen byte budget')
    client = LLMClient.from_pipeline_config(stage=stage, config_path=Path(config()['pipeline_config']))
    prices=read(OUT/'pricing_reference.json')['known_original_rates']
    if client.resolved.model in prices['models']:
        client.pricing=resolve_pricing_config({'pricing':prices},client.resolved.model)
    client.resolved = replace(client.resolved, max_retries=0, timeout_seconds=1200)
    client.audit_dir = dest / 'request_audit' / stage
    frozen_version=sha(OUT/'frozen_manifest.json')
    def signature_for(version,tokens):
        return digest({'workflow':version,'stage': stage, 'system': system, 'message': message, 'max_tokens': tokens,
            'provider': client.resolved.provider, 'model': client.resolved.model, 'api_format': client.resolved.api_format})
    def reusable_signatures():
        usable=set()
        for version in workflow_hashes():
            for tokens in (max_tokens,max(max_tokens,fallback_tokens)):
                usable.add(signature_for(version,tokens))
        return usable
    signature = signature_for(frozen_version,max_tokens)
    checkpoint = dest / 'tasks' / (task_id + '.json')
    if checkpoint.is_file():
        saved = read(checkpoint)
        reusable=reusable_signatures()
        if saved['signature'] in reusable or saved.get('base_signature') in reusable:
            if saved['signature']!=signature and saved.get('base_signature')!=signature:
                event(dest,{'event':'cache_reuse','task_id':task_id,'stage':stage,'basis':'prior_round_identical_inputs',
                    'current_signature':signature,'reused_signature':saved.get('signature')})
            return LLMJSONResponse(data=saved['data'], provider=saved['provider'], model=saved['model'])
        # Inputs changed this round (restored footnotes, regenerated directory):
        # archive the prior checkpoint, then make a fresh audited call.
        write(dest/'tasks_superseded'/(task_id+'.'+str(saved['signature'])[:12]+'.json'),saved)
        checkpoint.unlink()
        event(dest,{'event':'input_changed_recall','task_id':task_id,'stage':stage,
            'prior_signature':saved['signature'],'current_signature':signature})
    errors = [];retry_kinds=[];last_error_elapsed=0.0
    initial_signature = signature
    initial_max_tokens = max_tokens
    for attempt in range(1,4):
        if attempt > 1:
            if errors[-1]=='LLMOutputTruncatedError':
                larger=max(initial_max_tokens,fallback_tokens)
                if max_tokens>=larger:break
                max_tokens=larger
            elif retry_kinds[-1]=='request_or_transport':
                if retry_kinds.count('request_or_transport')>1:break
            elif errors[-1]=='UnexplainedEmptyResponseError':
                if errors.count('UnexplainedEmptyResponseError')>1:break
            else:break
            signature = signature_for(frozen_version,max_tokens)
        failed_path = dest / 'failed_tasks' / (task_id + f'_{attempt}.json')
        start = time.time(); history = len(client.call_history)
        event(dest, {'event': 'start', 'task_id': task_id, 'stage': stage, 'attempt': attempt,
            'signature': signature, 'input_bytes': input_size, 'input_budget_bytes': budget,
            'max_output_tokens': max_tokens, 'started_at': datetime.now(timezone.utc).isoformat(),
            'provider': client.resolved.provider, 'model': client.resolved.model,
            'timeout_seconds':client.resolved.timeout_seconds,
            'base_signature': initial_signature, 'output_budget_fallback': max_tokens>initial_max_tokens})
        print(dest.parent.name, dest.name, stage, task_id, f'attempt={attempt}', 'started', flush=True)
        try:
            response = client.call_json(system, message, max_tokens=max_tokens)
            write(dest/'parsed_attempts'/(task_id+f'_{attempt}.json'),response.data)
            if not isinstance(response.data, dict): raise ValueError('Response is not an object')
            if require_complete and response.data.get('has_more') is not False:
                raise ValueError('Response did not explicitly confirm complete output')
            if require_complete:
                if stage=='stage5_characterization' and 'observations' not in response.data and isinstance(response.data.get('spectrum_groups'),list):
                    response.data['observations']=[]
                required = (('sample_updates','state_samples','protocols','state_transitions','unresolved')
                    if stage=='stage3_sample_process' else
                    ('property_axes','subject_axes','condition_axes','cell_overrides','notes','unresolved','symbol_rules','field_decisions')
                    if stage=='stage4t_table_interpretation' else
                    ('observations','methods','unresolved') if stage=='stage5_characterization' else
                    ('observations','unresolved'))
                if any(not isinstance(response.data.get(k),list) for k in required):
                    raise ValueError('Required response arrays missing or malformed')
                from response_completion import validate
                validate(response.data,stage)
            write(checkpoint, {'signature': signature, 'data': response.data, 'provider': response.provider,
                'model': response.model, 'stage': stage, 'attempt': attempt,
                'base_signature':initial_signature,'max_output_tokens':max_tokens})
            event(dest, {'event': 'end', 'task_id': task_id, 'stage': stage, 'attempt': attempt,
                'signature': signature, 'success': True, 'elapsed_seconds': round(time.time()-start,3),
                'visible_answer_chars':len(client.last_raw_response.content or '') if client.last_raw_response else 0,
                'finish_reason':client.last_raw_response.finish_reason if client.last_raw_response else None,
                'usage': [asdict(x) for x in client.call_history[history:]]})
            print(dest.parent.name, dest.name, stage, task_id, 'completed', flush=True)
            return response
        except Exception as exc:
            error = type(exc).__name__; errors.append(error);last_error_elapsed=time.time()-start
            retry_kind='request_or_transport' if error=='LLMRequestError' or isinstance(exc,RequestException) else error
            retry_kinds.append(retry_kind)
            cause=exc
            seen=set()
            while cause.__cause__ is not None and id(cause) not in seen:
                seen.add(id(cause));cause=cause.__cause__
            cause_type=type(cause).__name__
            raw = client.last_raw_response
            write(failed_path, {'signature': signature, 'error_type': error, 'attempt': attempt, 'retry_kind':retry_kind, 'cause_type':cause_type,
                'raw_response': asdict(raw) if raw else None, 'same_input_retry': True})
            saved_failure=read(failed_path);saved_failure['elapsed_seconds']=round(last_error_elapsed,3)
            write(failed_path,saved_failure)
            event(dest, {'event': 'end', 'task_id': task_id, 'stage': stage, 'attempt': attempt,
                'signature': signature, 'success': False, 'error_type': error, 'retry_kind':retry_kind, 'cause_type':cause_type,
                'visible_answer_chars':len(raw.content or '') if raw else 0,
                'finish_reason':raw.finish_reason if raw else None,
                'elapsed_seconds': round(time.time()-start,3),
                'usage': [asdict(x) for x in client.call_history[history:]]})
            print(dest.parent.name, dest.name, stage, task_id, error, flush=True)
    raise AttemptsExhaustedError(errors)


def native_client(dest, stage):
    client = LLMClient.from_pipeline_config(stage=stage, config_path=Path(config()['pipeline_config']))
    counter = [0]
    def call(system, message, *, max_tokens=8192):
        counter[0] += 1
        return request(dest, f'{stage}_{counter[0]:03d}', stage, system, message,
            min(max_tokens, config()['native_max_output_tokens']), native=True, require_complete=False)
    client.call_json = call
    return client

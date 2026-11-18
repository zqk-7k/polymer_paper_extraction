"""Small frozen-table A/B: original values and axes, without standard-code gates."""
import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import time

from llm_client import LLMClient, load_pipeline_config, resolve_llm_config, resolve_pricing_config
from stages.sample_catalog import digest


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def score_case(case, response):
    observations = response.get('observations', []) if isinstance(response, dict) else []
    if not isinstance(observations, list):
        observations = []
    rows = []
    for label in case['labels']:
        matches = [r for r in observations if isinstance(r, dict) and r.get('source_cell_id') == label['source_cell_id']]
        failed = []
        if len(matches) != 1:
            failed.append('missing_or_duplicate_observation')
        else:
            for field, expected in label['expected'].items():
                actual = matches[0].get(field)
                if isinstance(expected, list) and isinstance(actual, list):
                    actual, expected = sorted(actual), sorted(expected)
                if actual != expected:
                    failed.append(field)
        rows.append({'source_cell_id': label['source_cell_id'], 'correct': not failed, 'failed_fields': failed})
    return {'reviewed_cells': len(rows), 'correct_cells': sum(r['correct'] for r in rows), 'rows': rows,
            'unexpected_cell_claims': sum(not isinstance(r, dict) or r.get('source_cell_id') not in {l['source_cell_id'] for l in case['labels']} for r in observations)}


def run(dataset, output_root, arm, model):
    dataset, output_root = Path(dataset), Path(output_root)
    if output_root.exists():
        raise ValueError('Output exists')
    raw_dataset = dataset.read_bytes()
    data = json.loads(raw_dataset)
    for path, expected in data['source_hashes'].items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
            raise ValueError('Frozen source changed')
    for case in data['cases']:
        if digest(case['request']) != case['request_sha256']:
            raise ValueError('Frozen request changed')
    config = load_pipeline_config()
    resolved = replace(resolve_llm_config(config, 'stage4_property'), model=model, requested_model=model,
                       max_retries=0, timeout_seconds=180)
    pricing = resolve_pricing_config(config, model) if model in config.get('pricing', {}).get('models', {}) else None
    result = {'schema_version': 'source_table_ab_run.v1', 'arm': arm, 'requested_model': model, 'status': 'running',
              'dataset_sha256': hashlib.sha256(raw_dataset).hexdigest(), 'cases': [], 'production_config_changed': False,
              'transport': {k: getattr(resolved, k) for k in ('api_format', 'stream', 'timeout_seconds', 'max_retries', 'thinking_effort')}}
    output_root.mkdir(parents=True)
    write(output_root / 'summary.json', result)
    for case in data['cases']:
        directory = output_root / case['case_id']
        directory.mkdir()
        write(directory / 'request.json', case['request'])
        client = LLMClient(resolved, pricing=pricing)
        row = {'case_id': case['case_id'], 'request_sha256': case['request_sha256'], 'status': 'running'}
        result['cases'].append(row)
        write(output_root / 'summary.json', result)
        print(json.dumps({'arm': arm, **row}), flush=True)
        started = time.monotonic()
        try:
            response = client.call_json(**case['request']).data
            write(directory / 'parsed_response.json', response)
            row.update(status='completed', score=score_case(case, response))
        except Exception as exc:
            row.update(status='failed', error_type=type(exc).__name__)
        row.update(elapsed_seconds=round(time.monotonic() - started, 3), api_requests=1)
        if client.last_raw_response is not None:
            raw = client.last_raw_response
            write(directory / 'raw_response.json', asdict(raw))
            row.update(actual_model=raw.model, finish_reason=raw.finish_reason,
                       cost=asdict(raw.cost) if raw.cost else None)
        write(directory / 'case_result.json', row)
        write(output_root / 'summary.json', result)
        print(json.dumps({'arm': arm, 'case_id': case['case_id'], 'status': row['status'], 'correct_cells': row.get('score', {}).get('correct_cells')}), flush=True)
    result.update(status='completed', original_inputs_unchanged=dataset.read_bytes() == raw_dataset and all(
        hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p, h in data['source_hashes'].items()))
    write(output_root / 'summary.json', result)
    return result


def compare(arm_a, arm_b, output_root):
    runs = [read(Path(p) / 'summary.json') for p in (arm_a, arm_b)]
    if any(r['status'] != 'completed' or not r['original_inputs_unchanged'] for r in runs):
        raise ValueError('Runs incomplete or inputs changed')
    if runs[0]['dataset_sha256'] != runs[1]['dataset_sha256'] or runs[0]['transport'] != runs[1]['transport']:
        raise ValueError('A/B inputs or settings differ')
    paired = set.intersection(*({c['case_id'] for c in r['cases'] if c['status'] == 'completed'} for r in runs))
    metrics = []
    for run_data in runs:
        completed = [c for c in run_data['cases'] if c['status'] == 'completed']
        metrics.append({'arm': run_data['arm'], 'model': run_data['requested_model'], 'requests': len(run_data['cases']),
            'completed_cases': len(completed), 'reviewed_cells': sum(c['score']['reviewed_cells'] for c in completed),
            'correct_cells': sum(c['score']['correct_cells'] for c in completed),
            'paired_correct_cells': sum(c['score']['correct_cells'] for c in completed if c['case_id'] in paired),
            'paired_reviewed_cells': sum(c['score']['reviewed_cells'] for c in completed if c['case_id'] in paired),
            'elapsed_seconds': round(sum(c['elapsed_seconds'] for c in run_data['cases']), 3),
            'costed_requests': sum(c.get('cost') is not None for c in run_data['cases']),
            'costs': [c['cost'] for c in run_data['cases'] if c.get('cost') is not None]})
    result = {'schema_version': 'source_table_ab_comparison.v1', 'same_frozen_inputs': True, 'paired_cases': sorted(paired),
              'metrics': metrics, 'production_model_replaced': False,
              'scope': '15 reviewed target cells across three difficult tables; development diagnostic, not population accuracy'}
    output = Path(output_root)
    output.mkdir(parents=True, exist_ok=False)
    write(output / 'summary.json', result)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest='command', required=True)
    r = commands.add_parser('run')
    for name in ('dataset', 'output-root', 'arm', 'model'):
        r.add_argument('--' + name, required=True)
    c = commands.add_parser('compare')
    for name in ('arm-a', 'arm-b', 'output-root'):
        c.add_argument('--' + name, required=True)
    args = vars(p.parse_args()); command = args.pop('command')
    (run if command == 'run' else compare)(**args)


if __name__ == '__main__':
    main()

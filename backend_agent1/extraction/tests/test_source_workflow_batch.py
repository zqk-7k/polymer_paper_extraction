import json
from pathlib import Path
from unittest.mock import patch

import batch_runner
from tools.source_workflow_batch import run_batch_workflow, forwarded_arguments


def test_full_pipeline_default_does_not_append_independent_calls(tmp_path):
    args = batch_runner.build_parser().parse_args([])
    assert not args.source_workflow and not args.source_workflow_only
    def forbidden(*args, **kwargs):
        raise AssertionError("Full pipeline must not append independent extraction")
    result = run_batch_workflow(args, output_dir=tmp_path, ref_nos=[],
                                config_path=tmp_path / "unused", workflow=forbidden)
    assert result["status"] == "disabled" and result["api_requests_this_run"] == 0


def test_defaults_and_forwarding_include_explicit_offline_and_model(tmp_path):
    args=batch_runner.build_parser().parse_args(['--source-workflow-offline','--source-workflow-only',
        '--source-workflow-model','glm-5.3-flash','--source-workflow-max-requests','4',
        '--source-workflow-context','full_article'])
    command=forwarded_arguments(args)
    assert args.source_workflow and '--source-workflow-only' in command
    assert '--source-workflow-offline' in command and 'glm-5.3-flash' in command
    assert command[command.index('--source-workflow-max-requests')+1]=='4'
    assert command[command.index('--source-workflow-context')+1]=='full_article'


def test_shared_hook_uses_selected_stage0_config_and_resumes_same_contract(tmp_path):
    stage=tmp_path/'stages';(stage/'reference_no_new').mkdir(parents=True)
    (stage/'reference_no_new/stage0_blocks.json').write_text('{}',encoding='utf8')
    config=tmp_path/'config.yaml';config.write_text('{}',encoding='utf8')
    args=batch_runner.build_parser().parse_args(['--source-workflow']);calls=[]
    def workflow(source,out,**kwargs):
        calls.append((source,out,kwargs));out.mkdir(parents=True,exist_ok=True)
        (out/'contract.json').write_text('{}')
        return {'status':'incomplete','pending_packets':2,'api_requests_this_run':1,
                'export_dir':str(out/'export'),'audit_dir':str(out/'audit'),'export_counts':{}}
    first=run_batch_workflow(args,output_dir=stage,ref_nos=['reference_no_new','reference_no_missing'],config_path=config,workflow=workflow)
    second=run_batch_workflow(args,output_dir=stage,ref_nos=['reference_no_new'],config_path=config,workflow=workflow)
    assert not first['execution_complete'] and first['missing_stage0_documents']==['reference_no_missing']
    assert not calls[0][2]['resume'] and calls[1][2]['resume']
    assert calls[0][2]['config_path']==config and calls[0][2]['max_requests']==20
    assert calls[0][2]['documents']==['reference_no_new'] and not calls[0][2]['retry_review']
    assert calls[0][2]['context_mode']=='article_once'
    args.source_workflow_context='full_article'
    run_batch_workflow(args,output_dir=stage,ref_nos=['reference_no_new'],config_path=config,workflow=workflow)
    assert calls[2][1]!=calls[1][1] and not calls[2][2]['resume']
    assert calls[2][2]['context_mode']=='full_article'


def test_validate_existing_never_triggers_new_model_calls(tmp_path):
    args=batch_runner.build_parser().parse_args(['--validate-existing','--source-workflow'])
    def forbidden(*args,**kwargs): raise AssertionError('Read-only validation must not call model workflow')
    assert run_batch_workflow(args,output_dir=tmp_path,ref_nos=[],config_path=tmp_path/'unused',workflow=forbidden)['status']=='skipped_read_only_validation'


def test_normal_batch_main_runs_hook_and_reports_partial_separately(tmp_path):
    inputs=tmp_path/'inputs';inputs.mkdir()
    (inputs/'reference_no_new_document.json').write_text('{}')
    config=tmp_path/'config.yaml';config.write_text('{}')
    summary=tmp_path/'summary.json'
    result={'status':'incomplete','execution_complete':False,'pending_packets':3,'api_requests_this_run':0}
    argv=['batch_runner.py','--config',str(config),'--input-dir',str(inputs),
          '--output-dir',str(tmp_path/'out'),'--summary-out',str(summary),'--source-workflow','--source-workflow-offline']
    with patch('sys.argv',argv),patch.object(batch_runner,'_worker_loop',return_value=0),patch.object(batch_runner,'run_batch_workflow',return_value=result) as hook:
        assert batch_runner.main()==1
    assert hook.call_args.kwargs['ref_nos']==['reference_no_new']
    saved=json.loads(summary.read_text(encoding='utf8'))
    assert saved['source_workflow']==result and not saved['acceptance']['accepted']
    assert 'legacy_acceptance' in saved and not saved['billing']['source_workflow_cost_included']

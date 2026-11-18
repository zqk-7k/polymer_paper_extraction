"""Shared options and a resumable post-stage hook for the existing batch entry."""
import argparse
import hashlib
import json
from pathlib import Path

from stages.sample_catalog import digest
from tools.run_source_workflow import run, workflow_rule_hashes, write


class _SourceWorkflowOnlyAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, True)
        namespace.source_workflow = True


def add_arguments(parser):
    parser.add_argument('--source-workflow',action=argparse.BooleanOptionalAction,default=False,
                        help='显式启用历史独立抽取分支；完整 Stage1–6 默认不追加调用')
    parser.add_argument('--source-workflow-model',default='deepseek-v4.1-flash')
    parser.add_argument('--source-workflow-context',choices=('article_once','local','full_article'),default='article_once',
                        help='默认每篇全文单次抽取、基础校验；local/full_article 是历史逐段模式')
    parser.add_argument('--source-workflow-max-requests',type=int,default=20,
                        help='本次通用流程调用预算，默认 20；整篇模式每篇一次，剩余文章留待续跑')
    parser.add_argument('--source-workflow-output',type=Path)
    parser.add_argument('--source-workflow-offline',action='store_true',help='只做离线组包、导出和检查，不调用正文模型')
    parser.add_argument('--source-workflow-only',action=_SourceWorkflowOnlyAction,nargs=0,default=False,
                        help='显式选择历史独立分支：只加载 Stage0，不执行 Stage1–6')


def forwarded_arguments(args):
    result=['--source-workflow' if args.source_workflow else '--no-source-workflow',
            '--source-workflow-model',args.source_workflow_model,
            '--source-workflow-context',args.source_workflow_context,
            '--source-workflow-max-requests',str(args.source_workflow_max_requests)]
    if args.source_workflow_output:
        result+=['--source-workflow-output',str(args.source_workflow_output.expanduser().resolve())]
    for name in ('source_workflow_offline','source_workflow_only'):
        if getattr(args,name):
            result.append('--'+name.replace('_','-'))
    return result


def run_batch_workflow(args, *, output_dir, ref_nos, config_path, workflow=run, asset_roots=()):
    if not args.source_workflow:
        return {'status':'disabled','execution_complete':True,'api_requests_this_run':0}
    if getattr(args,'validate_existing',False):
        return {'status':'skipped_read_only_validation','execution_complete':True,'api_requests_this_run':0}
    output_dir=Path(output_dir).resolve()
    root=(args.source_workflow_output or output_dir.with_name(output_dir.name+'_source_workflow')).resolve()
    if root==output_dir or root in output_dir.parents or output_dir in root.parents:
        raise ValueError('Source workflow output must be separate from stage output')
    present=[r for r in ref_nos if (output_dir/r/'stage0_blocks.json').is_file()]
    missing=sorted(set(ref_nos)-set(present))
    if not present:
        return {'status':'stage0_missing','execution_complete':False,
                'missing_stage0_documents':missing,'api_requests_this_run':0}
    identity={'sources':{r:hashlib.sha256((output_dir/r/'stage0_blocks.json').read_bytes()).hexdigest() for r in present},
              'source_root':str(output_dir),'model':args.source_workflow_model,'rules':workflow_rule_hashes(),
              'context_mode':args.source_workflow_context,
              'asset_roots':[str(Path(p).resolve()) for p in asset_roots],
              'config_hash':hashlib.sha256(Path(config_path).read_bytes()).hexdigest(),
              'schema_hash':hashlib.sha256((Path(__file__).resolve().parents[1]/'config/polymer_schema.yaml').read_bytes()).hexdigest()}
    directory=root/digest(identity)[:20]
    summary=workflow(output_dir,directory,model=args.source_workflow_model,documents=present,
                     input_kind='stage0',max_requests=args.source_workflow_max_requests,
                     offline=args.source_workflow_offline,resume=(directory/'contract.json').is_file(),
                     retry_review=args.source_workflow_context!='article_once',config_path=config_path,asset_roots=asset_roots,
                     context_mode=args.source_workflow_context)
    report={'status':summary['status'],'execution_complete':not missing and summary['pending_packets']==0,
            'summary_path':str(directory/'summary.json'),'export_dir':summary['export_dir'],
            'audit_dir':summary['audit_dir'],'pending_packets':summary['pending_packets'],
            'api_requests_this_run':summary['api_requests_this_run'],'missing_stage0_documents':missing,
            'export_counts':summary['export_counts'],'goal_complete':False,
            'cost_scope':'Workflow call costs are recorded separately under the workflow calls directory.'}
    root.mkdir(parents=True,exist_ok=True)
    write(root/'latest.json',report)
    return report

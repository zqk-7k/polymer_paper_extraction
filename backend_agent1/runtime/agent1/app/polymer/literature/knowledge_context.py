"""Share the workbench's component candidates without sharing mutable registry."""
from polymer.kernel import Kernel
from polymer.registry import Registry
from polymer.syntax import Parser
from polymer.knowledge_service import KnowledgeService
from polymer.knowledge_runtime import KnowledgeRegistry


def create_kernel(knowledge=None,policy='shared_component_candidates'):
    if policy not in ('shared_component_candidates','base_registry_only'):
        raise ValueError('LITERATURE_KNOWLEDGE_POLICY_INVALID')
    kernel=Kernel(Registry())
    context={'policy':policy,'namespace':'literature-knowledge-context/1.0','shared_registry_writes':False,
             'local_opsin_enabled':False,'network_enabled':False}
    if policy=='shared_component_candidates':
        knowledge=knowledge or KnowledgeService()
        try:
            snapshot=knowledge.snapshot('components')
            registry=KnowledgeRegistry(kernel.registry,knowledge,allow_opsin=False,max_calls=0)
            kernel.registry=registry;kernel.parser=Parser(registry)
            context.update(component_data_version=registry.version,available=snapshot['available'],reason=snapshot.get('reason_code'))
        except Exception:
            kernel.registry.close()
            raise
    kernel.literature_knowledge_context=context
    return kernel


def context_for(kernel):
    value=dict(getattr(kernel,'literature_knowledge_context',{'policy':'caller_supplied_kernel','namespace':'literature-knowledge-context/1.0'}))
    if hasattr(kernel.registry,'counters'):value['counters']=kernel.registry.counters()
    if hasattr(kernel.registry,'events'):value['resolution_events']=list(kernel.registry.events)
    return value

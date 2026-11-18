"""Wire verified MinerU documents into the existing literature service and Kernel."""
from copy import deepcopy
from threading import RLock
from polymer.common import ROOT
_LOCK=RLock()

def mineru_service(owner):
    from .mineru_bridge import MinerUService
    with _LOCK:
        if not hasattr(owner,'mineru'):
            owner.mineru=MinerUService(owner.store.root.parent/'mineru-ingest',ROOT/'.env')
        return owner.mineru

def approved_metadata(item):
    parser=item.get('parser')
    if parser is None:
        return {}
    if not isinstance(parser,dict):
        raise ValueError('PARSER_METADATA_OBJECT_REQUIRED')
    if parser.get('engine')!='MinerU':
        return {}
    from .mineru_bridge import MinerUService
    state=MinerUService(ROOT/'runs/mineru-ingest',ROOT/'.env').get(parser.get('job_id'))
    if state['status']!='COMPLETED':
        raise ValueError('MINERU_SOURCE_NOT_COMPLETED')
    source=state['document']
    if any(item.get(k)!=source.get(k) for k in ['name','role','text','input_sha256','pages']):
        raise ValueError('MINERU_DOCUMENT_SOURCE_MISMATCH')
    return {k:deepcopy(source[k]) for k in ['parser','source_assets','blocks','visual_regions'] if k in source}

import threading
import time

from tools.run_article_batch import execute


def test_bounded_concurrency_runs_each_article_once(tmp_path):
    source=tmp_path/'input'; config=tmp_path/'config.yaml'; config.write_text('{}')
    for i in range(7):
        doc=source/f'reference_no_{i}'; doc.mkdir(parents=True)
        (doc/'stage0_blocks.json').write_text('{}')
    lock=threading.Lock(); active=0; peak=0; seen=[]
    def workflow(src,out,**kwargs):
        nonlocal active,peak
        with lock: active+=1; peak=max(peak,active); seen.extend(kwargs['documents'])
        assert kwargs['max_requests']==1 and kwargs['context_mode']=='article_once'
        time.sleep(.04)
        with lock: active-=1
        return {'status':'text_scan_finished','pending_packets':0,'api_requests_this_run':1,
                'export_dir':str(out/'export_001'),'export_counts':{'model_extractions':2}}
    result=execute(source,tmp_path/'out',workers=5,config_path=config,workflow=workflow)
    assert result['successful_documents']==7 and result['api_requests_this_run']==7
    assert len(set(seen))==7 and 1<peak<=5

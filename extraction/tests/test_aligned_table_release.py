from types import SimpleNamespace
from stages import stage4_aligned_table_release as module


def test_aligned_rows_preserve_code_subrow_method_without_global_binding(monkeypatch):
    rows=[(0,0,'No.'),(0,1,'Codea'),(0,2,'Method'),(0,3,'PMT, °C.'),
          (1,0,'a'),(1,1,'P-A'),(1,2,'HTS'),(1,4,'250'),
          (2,0,'b'),(2,1,''),(2,2,'LTS'),(2,4,'260'),
          (3,0,'c'),(3,1,''),(3,2,''),(3,4,'270')]
    cells=[{'cell_id':f'T:r{r}:c{c}','row_index':r,'column_index':c,'text':s} for r,c,s in rows]
    element=SimpleNamespace(type='table',block_id='T',page=0,bbox=None,caption='Properties')
    monkeypatch.setattr(module,'Stage0Document',SimpleNamespace(model_validate=lambda _:SimpleNamespace(elements=[element])))
    class Cell:
        def __init__(self,d):self.d=d
        def model_dump(self,**kwargs):return self.d
    monkeypatch.setattr(module,'table_cells_for',lambda _: [Cell(c) for c in cells])
    monkeypatch.setattr(module,'shadow_extract_table',lambda _: {'header_rows':[0],'observations':[
        {'alignment_status':'paired_right_shift','property_name_normalized':'melting_temperature',
         'cell_id':f'T:r{r}:c4','row_index':r,'header_column_index':3} for r in [1,2,3]]})
    out,audit=module.recover_aligned_temperature_rows({'property_series':[]},{})
    pts=out['property_series'][0]['points']
    assert len(pts)==2
    assert all(p['sample_id'] is None and p['sample_resolution_status']=='unresolved' for p in pts)
    assert [p['coordinates'][1]['value_raw'] for p in pts]==['HTS','LTS']
    assert [p['coordinates'][2]['value_raw'] for p in pts]==['a','b']
    assert all(p['coordinates'][0]['value_raw']=='P-A' for p in pts)
    assert audit['decisions'][-1]['accepted'] is False
    replay,again=module.recover_aligned_temperature_rows(out,{})
    assert replay==out
    assert not any(d['accepted'] for d in again['decisions'])
    # The same source claim may already have converted numeric units.
    pts[0].update(value_min=523.15,value_max=523.15,unit_normalized='K')
    converted,again=module.recover_aligned_temperature_rows(out,{})
    assert converted==out
    assert not any(d['accepted'] for d in again['decisions'])

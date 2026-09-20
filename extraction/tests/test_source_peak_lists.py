from stages.stage4_direct_table_supplement import header_declared_peaks
from stages import source_peak_lists as module


def test_source_header_required_and_not_a_range_or_calculation():
    h = 'Fusion | Maxima of peaks in °C'
    assert [x['value'] for x in header_declared_peaks('49; 65', h)] == [49, 65]
    for bad in ['49-65', '49;65+2', '49,65', '49;49', '49;65;']:
        assert not header_declared_peaks(bad, h)
    for bad_h in ['Fusion in °C', 'Maxima of peaks in nm', 'Tg in °C']:
        assert not header_declared_peaks('49;65', bad_h)


def test_unique_source_sample_and_idempotent_recovery(monkeypatch):
    table = {'table_id': 'T', 'page': 0, 'caption': 'Measured DSC', 'cells': [
        {'cell_id':'s0','row_index':0,'column_index':0,'text':'Sample'},
        {'cell_id':'h','row_index':0,'column_index':1,'text':'Fusion peaks in °C'},
        {'cell_id':'s1','row_index':1,'column_index':0,'text':'A'},
        {'cell_id':'v1','row_index':1,'column_index':1,'text':'49; 65'}]}
    monkeypatch.setattr(module, 'table_requests', lambda _: [table])
    out, audit = module.recover_peak_lists({}, {})
    points = out['property_series'][0]['points']
    assert [p['value_min'] for p in points] == [49, 65]
    assert all(p['evidence'][0]['table_locator']['cell_id'] == 'v1' for p in points)
    assert all(p['measurement_context']['other_conditions']['full_source_cell'] == '49; 65' for p in points)
    assert all(p['sample_id'] is None for p in points)
    assert module.recover_peak_lists(out, {})[0] == out
    table['cells'].append({'cell_id':'s2','row_index':2,'column_index':0,'text':'A'})
    assert not module.recover_peak_lists({}, {})[0].get('property_series')


def test_slash_requires_explicit_double_transition_caption():
    h='Glass Transition Temperature Tg (°C)'
    note='Thermal transitions of blends (some samples show double transitions)'
    assert [p['value'] for p in header_declared_peaks('81/112',h,note)]==[81,112]
    assert not header_declared_peaks('81/112',h)
    assert not header_declared_peaks('81/112','Molecular weight ratio',note)
    assert not header_declared_peaks('81/112 + 3',h,note)


def test_blend_composition_and_processing_speed_joint_identity(monkeypatch):
    table={'table_id':'T','page':0,'caption':'Some samples show double transitions','cells':[
        {'cell_id':'sh','row_index':0,'column_index':0,'text':'Blend Composition (mol % PEN)'},
        {'cell_id':'ch','row_index':0,'column_index':1,'text':'Extruder Screw Speed (rpm)'},
        {'cell_id':'h','row_index':0,'column_index':2,'text':'Glass Transition Temperature Tg (°C)'},
        {'cell_id':'s1','row_index':1,'column_index':0,'text':'20'},
        {'cell_id':'c1','row_index':1,'column_index':1,'text':'18'},
        {'cell_id':'v1','row_index':1,'column_index':2,'text':'81/112'},
        {'cell_id':'s2','row_index':2,'column_index':0,'text':'20'},
        {'cell_id':'c2','row_index':2,'column_index':1,'text':'30'},
        {'cell_id':'v2','row_index':2,'column_index':2,'text':'82/113'}]}
    monkeypatch.setattr(module,'table_requests',lambda _:[table])
    out,_=module.recover_peak_lists({}, {})
    assert sum(len(s['points']) for s in out['property_series'])==4
    assert all(any(c['name_raw']=='source condition/state' for c in p['coordinates'])
               for s in out['property_series'] for p in s['points'])
    assert module.recover_peak_lists(out,{})[0]==out

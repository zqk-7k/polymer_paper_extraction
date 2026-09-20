from stages.source_verified_exponent_runs import verified_run_scales,repair_verified_exponent_runs


def fixture():
    cells=[{'cell_id':'reset1','row_index':1,'column_index':1,'text':r'$1.22\times 10^{-3}$'},
           {'cell_id':'v1','row_index':2,'column_index':1,'text':'2.41'},
           {'cell_id':'reset2','row_index':3,'column_index':1,'text':r'$1.03\times 10^{-1}$'},
           {'cell_id':'v2','row_index':4,'column_index':1,'text':'9.78'}]
    source={'elements':[{'block_id':'T1','type':'table','table_cells':cells}],
            'ocr':{'source_pdf_verification':{'version':'pdf-two-engine-transcription/1.0.0',
                'reference_values_accessed':False,'predictions_accessed':False,
                'shared_exponent_notations':[{'table_block_id':'T1','kind':'shared_scientific_notation_exponent',
                    'column_index':1,'reset_cell_ids':['reset1','reset2'],'applies_to_cell_ids':['v1','v2'],
                    'review_sha256':'abc','image_sha256':'def'}]}}}
    data={'properties':[{'value_raw':'9.78','value_min':9.78,'value_max':9.78,'unit_raw':'J/g/K',
                         'evidence':[{'block_id':'T1','table_locator':{'cell_id':'v2'}}]}]}
    return source,data


def test_certificate_not_physical_plausibility():
    source,data=fixture()
    scales=verified_run_scales(source)
    assert scales['v1']['factor']==.001 and scales['v2']['factor']==.1
    output,audit=repair_verified_exponent_runs(data,source)
    assert output['properties'][0]['value_min']==.978
    assert output['properties'][0]['value_raw']=='9.78'
    assert repair_verified_exponent_runs(output,source)[0]==output
    source['ocr']={}
    assert repair_verified_exponent_runs(data,source)[0]==data


def test_bad_certificate_does_not_repair():
    source,data=fixture()
    source['ocr']['source_pdf_verification']['shared_exponent_notations'][0]['reset_cell_ids'][1]='invented'
    assert not verified_run_scales(source)
    source,data=fixture()
    data['properties'][0]['unit_normalized']='cal/g/C'
    assert repair_verified_exponent_runs(data,source)[0]==data

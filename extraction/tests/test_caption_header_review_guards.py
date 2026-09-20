import copy
from stages.stage4_direct_table_supplement import caption_subject,caption_defines_property,attach_verified_header_scopes,header_applies

def test_caption_material_and_property_require_complete_tokens():
    point={'subject_caption_scope':'single_material_table','subject_caption_quote':'PEEK'}
    assert caption_subject({'caption':'Properties of PEEK-2000'},point) is None
    assert caption_subject({'caption':'Properties of PEEK'},point)=='PEEK'
    group={'property_name_raw':'contact angle'}
    assert not caption_defines_property({'caption':'Measurements of noncontact angle'},group)
    assert caption_defines_property({'caption':'Measurements of contact angle'},group)

def test_three_level_headers_keep_column_scope():
    top={'row_index':0,'column_index':1,'row_span':1,'column_span':2}
    unit={'row_index':1,'column_index':1,'row_span':1,'column_span':2}
    condition={'row_index':2,'column_index':2,'row_span':1,'column_span':1}
    a={'row_index':3,'column_index':1};b={'row_index':3,'column_index':2};other={'row_index':3,'column_index':3}
    assert all(header_applies(h,a) and header_applies(h,b) for h in [top,unit])
    assert not header_applies(condition,a) and header_applies(condition,b)
    assert not any(header_applies(h,other) for h in [top,unit,condition])

def test_conflicting_header_certificates_do_not_select_last_one():
    cells=[{'cell_id':'h','text':'Cp (J/g K)','row_index':0,'column_index':2},
        {'cell_id':'a','text':'1','row_index':2,'column_index':1},
        {'cell_id':'b','text':'2','row_index':2,'column_index':3}]
    scope={'table_id':'T','header_cell_id':'h','exact_header_text':'Cp (J/g K)',
           'applies_to_columns':[1],'source_image_sha256':'a'*64,'review_method':'codex_pdf_visual'}
    other=copy.deepcopy(scope);other['applies_to_columns']=[3]
    src={'ocr':{'source_header_scope_review':{'version':'pdf-header-scope/1.0.0',
        'reference_values_accessed':False,'predictions_accessed':False,'scopes':[scope,other]}}}
    attach_verified_header_scopes(cells,'T',src)
    assert '_pdf_verified_header_columns' not in cells[0]

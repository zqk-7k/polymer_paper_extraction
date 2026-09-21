from stages.stage4_direct_table_supplement import attach_verified_header_scopes, header_applies

def test_empty_denominator_layout_unit_is_not_a_real_fraction():
    from stages.stage4_direct_table_supplement import plain,unit_in_header
    assert unit_in_header('dL/g',r'$\eta_{inh}^{b)}$ $\frac{dL/g}{ }$')
    assert plain(r'\frac{a}{b}')!=plain('a')

def test_verified_centered_header_preserves_geometry_and_scope():
    h={'cell_id':'h','text':'Cp (J/g K)','row_index':0,'column_index':2,'column_span':1}
    a={'cell_id':'a','row_index':2,'column_index':1,'text':'9.78'}
    b={'cell_id':'b','row_index':2,'column_index':3,'text':'1.065'}
    t={'cell_id':'t','row_index':2,'column_index':0,'text':'300'}
    scope={'table_id':'T','header_cell_id':'h','exact_header_text':'Cp (J/g K)',
           'applies_to_columns':[1,3],'source_image_sha256':'a'*64,'review_method':'codex_pdf_visual'}
    src={'ocr':{'source_header_scope_review':{'version':'pdf-header-scope/1.0.0',
          'predictions_accessed':False,'reference_values_accessed':False,'scopes':[scope]}}}
    assert not header_applies(h,a)
    attach_verified_header_scopes([h,a,b,t],'T',src)
    assert header_applies(h,a) and header_applies(h,b) and not header_applies(h,t)
    assert (h['column_index'],h['column_span'])==(2,1)
    h.pop('_pdf_verified_header_columns');scope['exact_header_text']='wrong'
    attach_verified_header_scopes([h,a,b,t],'T',src)
    assert not header_applies(h,a)

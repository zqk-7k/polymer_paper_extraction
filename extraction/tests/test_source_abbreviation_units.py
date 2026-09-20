from stages.source_quantity_normalization import normalize_source_quantities, normalization_rule


def test_explicit_unit_abbreviations_preserve_values_and_original_units():
    for unit,target in [('dl./g.','dL/g'),('g./cc.','g/cm3'),('g/cc','g/cm3')]:
        data={'properties':[{'property_name_raw':'reported property','value_raw':'1.13',
            'value_min':1.13,'value_max':1.13,'unit_raw':unit,'unit_normalized':unit}]}
        out,audit=normalize_source_quantities(data)
        record=out['properties'][0]
        assert record['unit_raw']==unit and record['unit_normalized']==target
        assert record['value_raw']=='1.13' and record['value_min']==record['value_max']==1.13
        assert len(audit['changes'])==1
        again,report=normalize_source_quantities(out)
        assert again==out and not report['changes']


def test_missing_conflicting_and_unrelated_units_are_not_guessed():
    assert normalization_rule('viscosity','') is None
    assert normalization_rule('viscosity','cP') is None
    assert normalization_rule('density','g.') is None
    data={'properties':[{'property_name_raw':'viscosity','value_raw':'1.13',
        'value_min':1.13,'value_max':1.13,'unit_raw':'mL/g','unit_normalized':'dl./g.'}]}
    assert normalize_source_quantities(data)[0]==data

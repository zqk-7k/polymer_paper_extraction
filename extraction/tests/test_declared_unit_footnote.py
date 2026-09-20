from stages.stage4_direct_table_supplement import unit_in_header


def test_declared_temperature_unit_footnote():
    assert not unit_in_header('°C','Melting or softening point, °Ca')
    assert unit_in_header('°C','Melting or softening point, °Ca',r'$^{a}$ Determined by a hot-stage microscope.')
    assert not unit_in_header('°C','Melting or softening point, °Ca',r'$^{b}$ Determined by x-ray diffraction.')
    assert not unit_in_header('°C','Value °Carbon',r'$^{a}$ annotation')

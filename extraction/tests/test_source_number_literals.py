from stages.source_number_literals import scientific_literal


def test_complete_scientific_notation_is_one_literal():
    assert scientific_literal(r'$2.00 \times 10^{3}$')==2000
    assert scientific_literal('6 2 × 1 0 ^ {3}')==62000
    assert scientific_literal('4.5 × 10⁵')==450000
    assert scientific_literal('2.58 × 10⁻¹²')==2.58e-12


def test_does_not_evaluate_equations_ratios_or_partial_values():
    assert scientific_literal('M = 2.00 × 10^3') is None
    assert scientific_literal('2.00 × 10^3 / 7.5 × 10^5') is None
    assert scientific_literal('2.00 × 10^3 + 1') is None
    assert scientific_literal('2.00 × 10^999999') is None
    assert scientific_literal('2.00 × 10^3 g/mol') is None

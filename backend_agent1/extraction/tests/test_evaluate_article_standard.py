import pytest
from tools.evaluate_article_standard import numbers,property_key,compatible,value_match,pred_keys,source_confirmed_keys,source_standard_key


@pytest.mark.parametrize('raw,values,kind',[
    ('approximately 30,000 ~ 120,000',[30000,120000],'range'),
    ('1.2 × 10^-5',[1.2e-5],'scalar'),('5.73E(-12)',[5.73e-12],'scalar'),
    ('62.14 ± 3.93 J/m',[62.14],'scalar'),('1708',[1708],'scalar'),
    ('<5',[5],'less'),('100–200',[100,200],'range'),('7.1, 8.2',[7.1,8.2],'multiple'),
    ('0.2 nm^-1',[.2],'scalar'),('-20 °C',[-20],'scalar')])
def test_value_parsing(raw,values,kind):
    actual,k=numbers(raw)
    assert actual==pytest.approx(values) and k==kind


def test_match_keeps_units_ranges_and_subtypes_distinct():
    g={'minimum':.05166,'maximum':.05166,'unit':'GPa'}
    assert value_match(g,{'value_raw':'51.66 ± 0.55','unit_raw':'MPa'})[0]
    assert not value_match(g,{'value_raw':'51.66','unit_raw':'GPa'})[0]
    assert not value_match({'minimum':170,'maximum':170,'unit':'degree'},{'value_raw':'1708','unit_raw':'degree'})[0]
    assert not value_match({'minimum':5,'maximum':5,'unit':None},{'value_raw':'<5','unit_raw':None})[0]
    assert not value_match({'minimum':150,'maximum':150,'unit':'C'},{'value_raw':'100–200','unit_raw':'C'})[0]
    assert not compatible('mn','mw') and not compatible('dielectric_ac','dielectric_dc')
    assert pred_keys({'property_name_raw':'Mw/Mn','standard_property_name':'molecular_weight'})=={'dispersity'}
    assert pred_keys({'property_name_raw':'M_w/M_n','standard_property_name':'molecular_weight','property_subtype':'PDI'})=={'dispersity'}
    assert property_key('molecular_weight','Mn')=='mn'
    assert compatible('solution_viscosity','viscosity_inherent')
    assert not compatible('viscosity_intrinsic','viscosity_inherent')
    assert not compatible('surface_tension','surface_energy')


def test_source_confirmation_does_not_conflate_subtypes():
    p={'property_name_raw':'molecular weight','model_source_reference':{'quote':'Mn is about 30000'}}
    assert source_confirmed_keys(p)=={'molecular_weight','mn'}
    p['model_source_reference']['quote']='Mn and Mw were determined'
    assert source_confirmed_keys(p)=={'molecular_weight'}
    assert source_standard_key({'property_key':'surface_tension_polar','evidence_excerpt':'Surface Free Energies'})=='surface_energy_polar'
    assert source_standard_key({'property_key':'surface_tension','evidence_excerpt':'surface tension'})=='surface_tension'
    assert property_key('γ_s^p','polar')=='surface_energy_polar'


def test_explicit_unit_variants_and_temperature_rounding():
    assert value_match({'minimum':.26,'maximum':.26,'unit':'dL/g'},{'value_raw':'.26','unit_raw':'dl g−1'})[0]
    assert value_match({'minimum':118,'maximum':118,'unit':'°C'},{'value_raw':'391.2','unit_raw':'K'})[0]
    assert not value_match({'minimum':118,'maximum':118,'unit':'°C'},{'value_raw':'391.3','unit_raw':'K'})[0]
    assert value_match({'minimum':16000,'maximum':16000,'unit':None},{'value_raw':'1.6','unit_raw':'10^4'})[0]
    assert value_match({'minimum':.5,'maximum':.5,'unit':'dL/g'},{'value_raw':'.5','unit_raw':'dL·g−1'})[0]
    g={'minimum':350,'maximum':350,'unit':'C','raw_value':'>350 (dec.)'}
    assert value_match(g,{'value_raw':'>350 (dec.)','unit_raw':'C'})[0]
    assert not value_match(g,{'value_raw':'350','unit_raw':'C'})[0]
    assert numbers('172 700')==([172700],'scalar')
    assert value_match({'minimum':.017,'maximum':.017,'unit':'1/(ohm*cm)'},{'value_raw':'1.7 × 10^-2','unit_raw':'S/cm'})[0]
    assert value_match({'minimum':.00927,'maximum':.00927,'unit':'kcal/g'},{'value_raw':'38.8','unit_raw':'J/g'})[0]
    assert property_key('ΔHm')=='heat_fusion'

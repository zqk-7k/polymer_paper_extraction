import copy
import pytest

from schema.polymer_schema import PropertySeries
from stages.stage6_preview_salvage import series_point_issue_ids
from stages.stage6_validate_merge import validate_and_merge
from tests.test_stage6_validate_merge import all_stages


def pair():
    stages=list(all_stages())
    evidence=stages[4].properties[0].evidence[0].model_dump(mode='json')
    data={'series_id':'series001','sample_id':'s001','entity_id':'pe001',
          'sample_resolution_status':'resolved','property_name_raw':'stress',
          'measurement_context':{'condition_status':'not_reported'},
          'points':[{'point_id':'pt001','sample_id':'s001','entity_id':'pe001',
                     'sample_resolution_status':'resolved','coordinates':[],
                     'value_raw':'3.2','coverage_status':'covered',
                     'measurement_context':{'condition_status':'not_reported'},
                     'evidence':[evidence],'confidence':{'score':.8}}],
          'coverage':{'expected':1,'covered':1,'missing':0,'not_applicable':0,'ratio':1.},
          'evidence':[evidence],'confidence':{'score':.8}}
    second=copy.deepcopy(data);second['series_id']='series002'
    stages[4].property_series=[PropertySeries.model_validate(data),PropertySeries.model_validate(second)]
    return stages


@pytest.mark.parametrize('bad',['point_evidence','point_subject','parent_evidence'])
def test_invalid_local_point_does_not_reject_other_series_same_id(bad):
    stages=pair(); first=stages[4].property_series[0]
    if bad=='point_evidence':
        first.points[0].evidence[0].source_sentence='This invented sentence is not in the source document.'
    elif bad=='point_subject':first.points[0].sample_id='s999'
    else:first.evidence[0].source_sentence='This invented sentence is not in the source document.'
    final, validation=validate_and_merge(*stages,preview=True)
    assert final is not None and not validation.errors
    assert [s.series_id for s in final.property_series]==['series002']
    assert final.property_series[0].points[0].point_id=='pt001'
    rejected={x.object_id:x for x in final.rejected_objects}
    assert 'series001/pt001' in rejected
    assert 'series002/pt001' not in rejected
    assert rejected['series001/pt001'].raw_object['point_id']=='pt001'
    assert final.preview_publication_summary.conservation_passed
    assert final.preview_publication_summary.rejected_counts['property_series_point']==1


def test_unique_legacy_point_issue_ids_are_unchanged():
    stages=pair(); series=stages[4].property_series
    assert series_point_issue_ids(series)=={('series001','pt001'):'series001/pt001',
                                          ('series002','pt001'):'series002/pt001'}
    assert series_point_issue_ids(series[:1])=={('series001','pt001'):'pt001'}


def test_two_bad_points_have_two_rejections_and_conservation():
    stages=pair()
    for series in stages[4].property_series:
        series.points[0].evidence[0].source_sentence='This invented sentence is absent from the source.'
    final, validation=validate_and_merge(*stages,preview=True)
    assert final is not None and not validation.errors
    assert not final.property_series
    assert final.preview_publication_summary.conservation_passed
    assert final.preview_publication_summary.rejected_counts['property_series_point']==2

import importlib.util
from pathlib import Path
import sys
import unittest
PACKAGE=Path(__file__).resolve().parents[1]/'agent1_workflow'
sys.path.insert(0,str(PACKAGE))
from subject_scope import project,permits
from response_completion import validate,UnexplainedEmptyResponseError

class SubjectScopes(unittest.TestCase):
    def fixture(self):
        cells=[{'cell_id':f'c{r}{c}','row_index':r,'column_index':c,'text':v}
            for r,row in enumerate([['sample','Tg','sample','Tg'],['P1','120','P2','135']]) for c,v in enumerate(row)]
        task={'source_table':{'table_id':'t','caption':'Results for P1','cells':cells},'packet':{'evidence_sources':[]}}
        identity={'samples':[{'sample_id':'s1'},{'sample_id':'s2'}],'alias_index':{'p1':['s1'],'p2':['s2']}}
        axes=[{'axis':'row','indices':[1],'source_cell_ids':['c10'],'sample_id':'s1','owner_label_raw':'P1'},
              {'axis':'row','indices':[1],'source_cell_ids':['c12'],'sample_id':'s2','owner_label_raw':'P2'}]
        return task,identity,{'subject_axes':axes}
    def test_parallel_row_labels_separate_column_lanes(self):
        t,i,r=self.fixture();out,a=project(t,r,i)
        self.assertTrue(permits(out['subject_axes'][0]['region'],{'row_index':1,'column_index':1}))
        self.assertFalse(permits(out['subject_axes'][0]['region'],{'row_index':1,'column_index':3}))
        self.assertTrue(permits(out['subject_axes'][1]['region'],{'row_index':1,'column_index':3}))
        self.assertNotIn('region',r['subject_axes'][0])
    def test_invalid_region_holds_owner_without_deleting_axis(self):
        t,i,r=self.fixture();r['subject_axes'][0]['region']={'rows':[999],'columns':[1]}
        out,a=project(t,r,i);self.assertIsNone(out['subject_axes'][0]['sample_id']);self.assertEqual(len(out['subject_axes']),2)
    def test_table_scope_requires_named_quote(self):
        t,i,r=self.fixture();r={'subject_axes':[{'axis':'table','indices':[],'region':{'rows':[1],'columns':[1]},'sample_id':'s1','owner_label_raw':'P1','scope_evidence_refs':[{'source_id':'t','quote':'Results for P1'}]}]}
        out,a=project(t,r,i);self.assertEqual(out['subject_axes'][0]['sample_id'],'s1')
        r['subject_axes'][0]['scope_evidence_refs'][0]['quote']='missing'
        out,a=project(t,r,i);self.assertIsNone(out['subject_axes'][0]['sample_id'])
    def test_valid_existing_single_axis_unchanged(self):
        t,i,r=self.fixture();r['subject_axes']=r['subject_axes'][:1]
        out,a=project(t,r,i);self.assertEqual(out,r);self.assertEqual(a,[])
    def test_parent_and_child_headers_are_not_parallel_lanes(self):
        t,i,r=self.fixture()
        r['subject_axes']=[{'axis':'column','indices':[1,2,3],'source_cell_ids':['c01'],'owner_label_raw':'Tg'},
            {'axis':'column','indices':[1],'source_cell_ids':['c11'],'owner_label_raw':'120'}]
        out,a=project(t,r,i);self.assertEqual(out,r);self.assertEqual(a,[])

class CompletionTests(unittest.TestCase):
    def test_empty_unexplained_is_failure(self):
        with self.assertRaises(UnexplainedEmptyResponseError):validate({'observations':[],'unresolved':[]},'stage4_property')
    def test_empty_explained_allowed_without_claiming_source_absence(self):
        d={'observations':[],'unresolved':[],'completion_explanation':{'scope':'all_supplied_sources','reason':'No thermal properties reported in this supplied field group.'}}
        validate(d,'stage4_property')
    def test_unresolved_and_spectral_groups_are_not_empty(self):
        validate({'observations':[],'unresolved':[{'reason':'owner unknown'}]},'stage4_property')
        validate({'spectrum_groups':[{'peaks':[{'value_raw':'120'}]}]},'stage5_characterization')

if __name__=='__main__':unittest.main()

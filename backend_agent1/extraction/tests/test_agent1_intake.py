"""Intake boundaries and native-default preservation, with no API requests."""
import argparse
import json
from pathlib import Path
import tempfile
import unittest
from agent1_workflow.api import add_arguments,forwarded_arguments,validate_bundle,prepare,write

class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.raw={'document_id':'reference_no_001','source_document_schema_version':'1.0','elements':[
            {'block_id':'p1','source_block_index':0,'type':'text','text':'P1 film'}]}
        self.entities={'document_id':'reference_no_001','polymer_entities':[{'entity_id':'e1','evidence':{'block_id':'p1'}}]}
        self.samples={'document_id':'reference_no_001','samples':[{'sample_id':'s1','refers_to_entity':'e1','evidence':{'block_id':'p1'}}]}
        self.handoff={'identities':[{'sample_id':'s1'}]}
        self.bundle=self.root/'bundles/reference_no_001';self.save()
    def tearDown(self):self.tmp.cleanup()
    def save(self):
        for n,v in [('agent1_entities.json',self.entities),('agent1_directory_samples.json',self.samples),('agent1_handoff.json',self.handoff)]:write(self.bundle/n,v)
    def test_default_native(self):
        p=argparse.ArgumentParser();add_arguments(p)
        self.assertEqual(forwarded_arguments(p.parse_args([])),['--directory-source','native'])
    def test_valid_bundle(self):self.assertEqual(len(validate_bundle(self.raw,self.bundle)[1]['samples']),1)
    def test_missing_bundle_fails(self):
        (self.bundle/'agent1_handoff.json').unlink()
        with self.assertRaisesRegex(ValueError,'no native fallback'):validate_bundle(self.raw,self.bundle)
    def test_document_mismatch(self):
        self.entities['document_id']='reference_no_002';self.save()
        with self.assertRaisesRegex(ValueError,'identity mismatch'):validate_bundle(self.raw,self.bundle)
    def test_duplicate_samples(self):
        self.samples['samples']*=2;self.save()
        with self.assertRaisesRegex(ValueError,'Duplicate'):validate_bundle(self.raw,self.bundle)
    def test_dangling_entity(self):
        self.samples['samples'][0]['refers_to_entity']='e9';self.save()
        with self.assertRaisesRegex(ValueError,'Dangling'):validate_bundle(self.raw,self.bundle)
    def test_handoff_member_mismatch(self):
        self.handoff['identities']=[];self.save()
        with self.assertRaisesRegex(ValueError,'membership mismatch'):validate_bundle(self.raw,self.bundle)
    def test_foreign_source(self):
        self.entities['polymer_entities'][0]['evidence']['block_id']='other';self.save()
        with self.assertRaisesRegex(ValueError,'block missing'):validate_bundle(self.raw,self.bundle)
    def test_source_version_drift(self):
        wrong=json.loads(json.dumps(self.raw));wrong['elements'][0]['text']='P2 film'
        write(self.bundle/'stage0_blocks.json',wrong)
        with self.assertRaisesRegex(ValueError,'source version'):validate_bundle(self.raw,self.bundle)
    def test_resume_contract_and_safe_destination(self):
        doc=self.root/'stage0.json';write(doc,self.raw)
        config=self.root/'pipeline.yaml';config.write_text('stages: {}',encoding='utf-8')
        out=self.root/'output'
        first=prepare([doc],self.bundle.parent,out,config)
        self.assertEqual(prepare([doc],self.bundle.parent,out,config),first)
        self.samples['samples'][0]['sample_label_raw']='different';self.save()
        with self.assertRaisesRegex(ValueError,'different contract'):prepare([doc],self.bundle.parent,out,config)
    def test_nonempty_output_rejected(self):
        doc=self.root/'stage0.json';write(doc,self.raw)
        config=self.root/'pipeline.yaml';config.write_text('stages: {}',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'empty output'):prepare([doc],self.bundle.parent,self.root,config)

if __name__=='__main__':unittest.main()

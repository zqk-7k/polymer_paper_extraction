import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pipeline_runner
import pipeline_default

class RoutingTests(unittest.TestCase):
    def test_default_uses_agent1(self):
        with patch('pipeline_default.main',return_value=0) as new, patch.object(pipeline_runner,'legacy_main') as old:
            self.assertEqual(pipeline_runner.main(['--input-dir','x']),0)
            new.assert_called_once_with(['--input-dir','x']);old.assert_not_called()
    def test_source_only_cannot_recurse(self):
        with patch.object(pipeline_runner,'legacy_main',return_value=0) as old,patch('pipeline_default.main') as new:
            pipeline_runner.main(['--workflow','source-only','--input-dir','x'])
            self.assertIn('--skip-extraction',old.call_args.args[0]);new.assert_not_called()
    def test_legacy_explicit(self):
        with patch.object(pipeline_runner,'legacy_main',return_value=0) as old,patch('pipeline_default.main') as new:
            pipeline_runner.main(['--workflow','legacy','--input-dir','x'])
            old.assert_called_once_with(['--input-dir','x']);new.assert_not_called()
    def test_unknown_old_options_fail_before_execution(self):
        with patch('pipeline_default.subprocess.run') as run,self.assertRaises(SystemExit):
            pipeline_default.main(['--force'])
        run.assert_not_called()
    def test_completed_resume_makes_no_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/'pdf_contract.json').write_text(json.dumps({'frozen_files':{}}),'utf8')
            with patch('pipeline_default.bridge.status',return_value={'completed':True}),patch('pipeline_default.subprocess.run') as run:
                self.assertEqual(pipeline_default.main(['--resume','--output-dir',tmp]),0)
                run.assert_not_called()
    def test_resume_rejects_new_inputs(self):
        with patch('pipeline_default.subprocess.run') as run,self.assertRaises(SystemExit):
            pipeline_default.main(['--resume','--output-dir','x','--input-dir','y'])
        run.assert_not_called()

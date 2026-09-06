import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('model_screen', Path(__file__).with_name('run.py'))
screen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(screen)

class ScreenTests(unittest.TestCase):
    def good(self):
        return {'cases': [{'id': key, 'classification': value[0], 'action': value[1], 'evidence_ids': sorted(value[2]), 'explanation': 'Synthetic'} for key, value in screen.EXPECTED.items()]}

    def test_matches_exact_ids_not_position(self):
        response = self.good()
        response['cases'].reverse()
        self.assertTrue(screen.evaluate(response)['all_pass'])

    def test_missing_extra_duplicate_and_unknown_ids_fail(self):
        values = []
        missing = self.good(); missing['cases'].pop(); values.append(missing)
        extra = self.good(); extra['cases'].append(extra['cases'][0]); values.append(extra)
        duplicate = self.good(); duplicate['cases'][-1]['id'] = '1'; values.append(duplicate)
        unknown = self.good(); unknown['cases'][-1]['id'] = '9'; values.append(unknown)
        for value in values:
            with self.assertRaises(ValueError): screen.evaluate(value)

    def test_missing_wrong_and_invented_evidence_do_not_pass(self):
        for evidence in ([], ['E99'], ['E1', 'E2', 'E99'], ['E1', 'E2', 'E1']):
            response = self.good(); response['cases'][0]['evidence_ids'] = evidence
            self.assertFalse(screen.evaluate(response)['all_pass'])
        response = self.good(); response['cases'][0]['action'] = 'wrong'
        self.assertFalse(screen.evaluate(response)['all_pass'])

    def test_no_raw_events_in_summary(self):
        events = json.dumps({'type':'turn.completed','usage':{'input_tokens':1,'unknown':'private','output_tokens':2}}) + '\n' + json.dumps({'type':'tool.output','text':'private'})
        self.assertEqual([{'input_tokens':1,'output_tokens':2}], screen.sanitized_usage(events))

    def test_run_contract_uses_fake_command_no_model(self):
        import subprocess
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            def fake(argv, **kwargs):
                self.assertIn('--ignore-user-config', argv)
                self.assertIn('--sandbox', argv)
                target = Path(argv[argv.index('--output-last-message') + 1])
                target.write_text(json.dumps(self.good()))
                return subprocess.CompletedProcess(argv, 0, '{"type":"turn.completed","usage":{"input_tokens":5}}\n', '')
            with patch.object(screen.subprocess, 'run', side_effect=fake):
                self.assertTrue(screen.run_once('/fake/codex', 'synthetic-model', 'high', directory)['all_pass'])

if __name__ == '__main__': unittest.main()

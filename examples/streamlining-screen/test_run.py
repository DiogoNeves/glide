import contextlib,importlib.util,io,json,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('streamlining_screen',ROOT/'run.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)

class BehaviorScreenTests(unittest.TestCase):
 def setUp(self):
  runner.CODEX=Path('/usr/bin/false')
  self.cases=json.loads((ROOT/'cases.json').read_text())
  self.daily=[c for c in self.cases if c['group']=='daily']
  self.answer={'cases':[dict(case_id=c['id'],user_response='',proposed_actions=[],evidence_ids=[c['evidence'][0]['id']],uncertainties=[]) for c in self.daily]}
 def test_unique_complete_fixtures(self):
  self.assertEqual(len(self.cases),50)
  self.assertEqual(len({c['id'] for c in self.cases}),50)
  for c in self.cases:
   self.assertTrue(c['required']);self.assertTrue(c['forbidden']);self.assertTrue(c['evidence'])
 def test_exact_case_ids_and_local_evidence(self):
  self.assertTrue(runner.validate_answer(self.answer,self.daily))
  self.answer['cases'][0]['evidence_ids']=['2.1']
  self.assertFalse(runner.validate_answer(self.answer,self.daily))
 def test_missing_duplicate_or_malformed_answer(self):
  self.answer['cases'].append(self.answer['cases'][0])
  self.assertFalse(runner.validate_answer(self.answer,self.daily))
  self.answer['cases']=self.answer['cases'][1:]
  self.answer['cases'][0]['proposed_actions']='tool receipt'
  self.assertFalse(runner.validate_answer(self.answer,self.daily))
 def test_actual_tool_event_fails_and_rubric_is_hidden(self):
  with tempfile.TemporaryDirectory() as name:
   directory=Path(name);(directory/'baseline-daily-policy.txt').write_text('PUBLIC TEST POLICY')
   runner.POLICY=directory;runner.OUTPUT=directory/'output'
   def fake_run(argv,**kwargs):
    payload=kwargs['input']
    self.assertNotIn('manufactured finding; redundant digest',payload)
    self.assertIn('features.shell_tool=false',argv);self.assertIn('features.unified_exec=false',argv)
    self.assertIn('--ignore-user-config',argv);self.assertIn('--ignore-rules',argv)
    Path(argv[argv.index('--output-last-message')+1]).write_text(json.dumps(self.answer))
    return SimpleNamespace(returncode=0,stdout=json.dumps({'type':'item.completed','item':{'type':'command_execution','command':'echo forbidden'}})+'\n'+json.dumps({'type':'turn.completed','usage':{'input_tokens':4,'output_tokens':3,'unexpected_private_field':'hidden'}}),stderr='')
   with patch.object(runner.subprocess,'run',side_effect=fake_run):
    result=runner.execute('baseline','daily','fixture','test-model','high')
   self.assertTrue(result['schema_valid']);self.assertFalse(result['hard_gate_no_actual_tools'])
   self.assertEqual(result['usage'],[{'input_tokens':4,'output_tokens':3}])
   with self.assertRaises(ValueError):runner.execute('baseline','daily','fixture','test-model','high')
 def test_failed_model_is_not_a_quality_pass(self):
  with tempfile.TemporaryDirectory() as name:
   directory=Path(name);(directory/'baseline-daily-policy.txt').write_text('PUBLIC TEST POLICY')
   runner.POLICY=directory;runner.OUTPUT=directory/'output'
   with patch.object(runner.subprocess,'run',return_value=SimpleNamespace(returncode=1,stdout='{"type":"turn.failed"}',stderr='unsupported model')):
    result=runner.execute('baseline','daily','failure','test-model','high')
   self.assertEqual(result['exit_code'],1);self.assertFalse(result['schema_valid'])
   self.assertEqual((directory/'output/failure/baseline-daily/stderr.txt').read_text(),'unsupported model')
 def test_unknown_activity_and_timeout_are_retained(self):
  with tempfile.TemporaryDirectory() as name:
   directory=Path(name);(directory/'baseline-daily-policy.txt').write_text('PUBLIC TEST POLICY')
   runner.POLICY=directory;runner.OUTPUT=directory/'output'
   with patch.object(runner.subprocess,'run',return_value=SimpleNamespace(returncode=1,stdout=json.dumps({'type':'item.completed','item':{'type':'future_external_tool'}}),stderr='')):
    result=runner.execute('baseline','daily','unknown','test-model','high')
   self.assertFalse(result['hard_gate_no_actual_tools'])
   with patch.object(runner.subprocess,'run',side_effect=subprocess.TimeoutExpired(['codex'],600,output=b'partial events',stderr=b'timeout evidence')):
    result=runner.execute('baseline','daily','timeout','test-model','high')
   self.assertEqual(result['error'],'TimeoutExpired');self.assertFalse(result['schema_valid'])
   self.assertEqual((directory/'output/timeout/baseline-daily/events.jsonl').read_text(),'partial events')
 def test_missing_usage_or_transmission_optin_stops_before_cli(self):
  with tempfile.TemporaryDirectory() as name:
   argv=['run.py','--codex','/usr/bin/false','--policy-dir',name,'--output',name+'/output','--run-id','optin','--group','daily','--model','test-model']
   for extra in [[],['--allow-model-usage'],['--approved-policy-transmission']]:
    with patch.object(sys,'argv',argv+extra),patch.object(runner.subprocess,'run') as process,contextlib.redirect_stderr(io.StringIO()):
     with self.assertRaises(SystemExit) as exit_:runner.main()
     self.assertEqual(exit_.exception.code,2);process.assert_not_called()
if __name__=='__main__':unittest.main()

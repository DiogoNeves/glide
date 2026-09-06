import hashlib
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest

from glide_memory import Store, StoreError
from glide_memory import overlays


class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='glide-overlay-', dir='/private/tmp' if Path('/private/tmp').exists() else None)
        self.root = Path(self.tmp.name)
        self.vault = self.root / 'vault'
        self.vault.mkdir()
        self.source = self.vault / 'Fictional field notes.md'
        self.source.write_text('Specimen labels are useful for locating experimental samples.')
        self.evidence = [{'path': self.source.name, 'sha256': hashlib.sha256(self.source.read_bytes()).hexdigest(), 'quote': 'Specimen labels are useful'}]
        self.store = Store.initialize(self.vault, self.root / 'state')
        self.store.activate_writer(old_writer_stopped=True)
        records = [{'id': 'specimen', 'title': 'Specimen labels', 'body': 'The fictional specimen labels support a lab trial.', 'sources': self.evidence}, {'id': 'unrelated', 'title': 'Other experiment', 'body': 'The unrelated field experiment has a different purpose.', 'sources': self.evidence}]
        proposal = self.store.propose(records, expected_revisions={'specimen': 0, 'unrelated': 0}, rationale='Synthetic fixture', idempotency_key='fixtures')
        self.store.apply(proposal['proposal_id'])
        self.cases = self.root / 'frozen-cases.json'
        self.cases.write_text(json.dumps({'schema': 1, 'cases': [{'id': 'known', 'split': 'regression', 'query': 'specimen', 'expected_ids': ['specimen']}, {'id': 'alias', 'split': 'heldout', 'query': 'sample inventory', 'expected_ids': ['specimen']}]}))
        self.change = {'retrieval_aliases': {'sample inventory': ['specimen']}}

    def tearDown(self):
        self.tmp.cleanup()

    def enable(self):
        self.store.config['learned_overlays'] = {'enabled': True, 'cases_path': str(self.cases), 'cases_sha256': hashlib.sha256(self.cases.read_bytes()).hexdigest()}
        self.store._save_config()

    def activate(self, key='improve'):
        return overlays.activate(self.store, self.change, evidence=self.evidence, rationale='The frozen recall case demonstrated a useful synonym.', idempotency_key=key)

    def test_opt_in_frozen_tests_and_real_improvement_gate(self):
        with self.assertRaises(StoreError):
            self.activate()
        self.enable()
        report = overlays.evaluate(self.store, self.change)
        self.assertTrue(report['accepted'])
        self.assertFalse(report['baseline'][1]['passed'])
        self.assertTrue(report['candidate'][1]['passed'])
        receipt = self.activate()
        self.assertTrue(receipt['committed'])
        self.assertEqual(['specimen'], [r['id'] for r in self.store.search('sample inventory', include_sources=False)])
        self.assertEqual(receipt['bundle'], self.activate()['bundle'])
        self.assertTrue(self.store.verify()['ok'])
        before = self.store.export()
        self.store.db_path.unlink()
        self.store.rebuild()
        self.assertEqual(before, self.store.export())
        self.assertEqual('ai', self.store.get(overlays.RECORD_ID)['origin'])

    def test_rollback_is_durable_and_weekly_budget_cannot_be_reset(self):
        self.enable()
        self.activate()
        receipt = overlays.rollback(self.store, evidence=self.evidence, rationale='The owner observed an unwanted retrieval expansion.', idempotency_key='rollback')
        self.assertTrue(receipt['committed'])
        self.assertEqual([], self.store.search('sample inventory', include_sources=False))
        with self.assertRaisesRegex(StoreError, 'weekly'):
            self.activate(key='retry-after-rollback')
        self.assertEqual(2, len(self.store.history(overlays.RECORD_ID)))

    def test_rollback_survives_broken_evaluator_and_is_idempotent(self):
        self.enable()
        self.activate()
        self.cases.unlink()
        self.store.config['learned_overlays']['enabled'] = False
        self.store._save_config()
        result = overlays.rollback(self.store, evidence=self.evidence, rationale='Observed regression; evaluator unavailable', idempotency_key='recover')
        repeated = overlays.rollback(self.store, evidence=self.evidence, rationale='Observed regression; evaluator unavailable', idempotency_key='recover')
        self.assertEqual(result['bundle'], repeated['bundle'])
        self.assertEqual([], self.store.search('sample inventory', include_sources=False))

    def test_failed_candidate_receipt_prevents_repeated_automatic_attempts(self):
        self.enable()
        with self.assertRaisesRegex(StoreError, 'durably recorded'):
            overlays.activate(self.store, {'retrieval_aliases': {}}, evidence=self.evidence, rationale='A candidate with no measured benefit', idempotency_key='bad-candidate')
        self.assertEqual('typed-overlay-review', self.store.history()[-1]['actor'])
        with self.assertRaisesRegex(StoreError, 'weekly'):
            self.activate(key='another-candidate')
        self.assertEqual([], self.store.search('sample inventory', include_sources=False))

    def test_concurrent_failed_candidates_share_one_weekly_attempt_budget(self):
        self.enable()
        def attempt(key):
            store = Store.from_config(self.store.config_path)
            try:
                overlays.activate(store, {'retrieval_aliases': {}}, evidence=self.evidence, rationale='A candidate with no measured benefit', idempotency_key=key)
            except StoreError as error:
                return str(error)
            return 'unexpected success'
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(attempt, ['candidate-a', 'candidate-b']))
        self.assertEqual(1, sum('durably recorded' in value for value in results))
        self.assertEqual(1, sum('weekly' in value for value in results))
        self.assertEqual(1, sum(event['actor'] == 'typed-overlay-review' for event in self.store.history()))

    def test_typed_boundary_and_case_integrity(self):
        self.enable()
        for change in ({'permissions': 'allow all'}, {'skill_text': 'Change the instructions'}, {'context_priority': ['missing']}, {'retrieval_aliases': {'q': ['a'] * 4}}):
            with self.assertRaises(StoreError):
                overlays.evaluate(self.store, change)
        self.cases.write_text(self.cases.read_text() + '\n')
        with self.assertRaisesRegex(StoreError, 'changed'):
            self.activate()

    def test_caller_cannot_submit_pass_flag_or_bypass_reserved_workflow(self):
        self.enable()
        with self.assertRaises(StoreError):
            overlays.activate(self.store, {'retrieval_aliases': {'sample inventory': ['irrelevant']}, 'passed': True}, evidence=self.evidence, rationale='Untrusted claim of success', idempotency_key='bad')
        with self.assertRaises(StoreError):
            self.store.propose([{'id': overlays.RECORD_ID, 'title': 'Attempted bypass', 'body': 'Arbitrary change', 'kind': 'workflow', 'sources': self.evidence}], expected_revisions={overlays.RECORD_ID: 0}, rationale='Bypass', idempotency_key='bypass')
        with self.assertRaisesRegex(StoreError, 'rejected'):
            overlays.activate(self.store, {'retrieval_aliases': {}}, evidence=self.evidence, rationale='No measured improvement', idempotency_key='nothing')


if __name__ == '__main__':
    unittest.main()

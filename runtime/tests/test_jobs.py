import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from glide_memory import Store, StoreError, ConflictError
from glide_memory.jobs import checkpoint_id, job_inputs, finish_job
from glide_memory.pipeline import _body


class JobTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='glide-jobs-', dir='/private/tmp' if Path('/private/tmp').is_dir() else None)
        root = Path(self.temporary.name)
        self.vault = root / 'vault'
        self.vault.mkdir()
        source = self.vault / 'Fictional lab observation.md'
        source.write_text('The fictional laboratory recorded observations about specimen labels.')
        self.evidence = [{'path': source.name, 'sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'quote': 'observations about specimen labels'}]
        self.store = Store.initialize(self.vault, root / 'local')
        self.store.config.update(knowledge_review='automatic', automatic_source_prefixes=[source.name])
        self.store._save_config()
        self.store.activate_writer(old_writer_stopped=True)

    def tearDown(self):
        self.temporary.cleanup()

    def record(self, rid, body='A qualified interpretation of the fictional specimen trial.', **extras):
        return {'id': rid, 'title': rid, 'body': body, 'kind': 'knowledge', 'sources': self.evidence, **extras}

    def add(self, rid, **extras):
        proposal = self.store.propose([self.record(rid, **extras)], expected_revisions={rid: 0}, rationale='Synthetic input', idempotency_key=rid)
        return self.store.apply(proposal['proposal_id'])

    def finish(self, inputs, records=None, key='finish', expected=None):
        records = records or []
        expected = expected or {inputs['checkpoint_id']: inputs['checkpoint_revision'], **{r['id']: 0 for r in records}}
        return finish_job(self.store, inputs['job_id'], inputs['processed_through'], records, expected, 'Reviewed this bounded set of inputs.', self.evidence, key)

    def test_no_change_creates_no_receipt_loop_and_checkpoint_ids_are_reserved(self):
        before = self.store.export()
        inputs = job_inputs(self.store, 'dream')
        self.assertFalse(inputs['has_work'])
        self.assertFalse(self.finish(inputs)['committed'])
        self.assertEqual(before, self.store.export())
        with self.assertRaises(StoreError):
            self.store.propose([self.record(checkpoint_id('dream'))], expected_revisions={checkpoint_id('dream'): 0}, rationale='Invalid bypass', idempotency_key='bypass')
        with self.assertRaises(StoreError):
            job_inputs(self.store, 'unknown')
        with self.assertRaises(StoreError):
            job_inputs(self.store, 'dream', batch_limit=51)

    def test_partial_batches_and_new_input_are_not_consumed(self):
        first = self.add('first')
        second = self.add('second')
        inputs = job_inputs(self.store, 'dream', batch_limit=1)
        self.assertEqual(first['bundle'], inputs['processed_through'])
        self.assertEqual(1, inputs['pending_count'])
        third = self.add('arrived-later')
        receipt = self.finish(inputs, [self.record('synthesis')])
        self.assertTrue(receipt['committed'])
        pending = job_inputs(self.store, 'dream')
        self.assertEqual([second['bundle'], third['bundle']], [b['bundle'] for b in pending['bundles']])
        self.assertNotIn('synthesis', [r['id'] for b in pending['bundles'] for r in b['records']])
        self.finish(pending, key='catch-up')
        self.assertFalse(job_inputs(self.store, 'dream')['has_work'])
        self.assertEqual(receipt['bundle'], self.finish(inputs, [self.record('synthesis')])['bundle'])

    def test_output_and_cursor_are_atomic_across_failure_and_stale_completion(self):
        self.add('input')
        first = job_inputs(self.store, 'daily')
        with mock.patch.object(self.store, 'apply', side_effect=OSError('failed before commit')):
            with self.assertRaises(OSError):
                self.finish(first, [self.record('output')])
        self.assertEqual(0, job_inputs(self.store, 'daily')['checkpoint_revision'])
        self.assertTrue(job_inputs(self.store, 'daily')['has_work'])
        receipt = self.finish(first, [self.record('output')])
        bundle = next(b for b in self.store._load()['bundles'] if b['hash'] == receipt['bundle'])
        self.assertEqual({'output', checkpoint_id('daily')}, {r['id'] for r in bundle['records']})
        with self.assertRaises(ConflictError):
            self.finish(first, [self.record('other')], key='stale')
        self.assertFalse(job_inputs(self.store, 'daily')['has_work'])
        self.store.db_path.unlink()
        self.store.rebuild()
        self.assertFalse(job_inputs(self.store, 'daily')['has_work'])

    def test_checkpoint_noise_is_excluded_but_other_job_semantic_outputs_count(self):
        self.add('input')
        self.finish(job_inputs(self.store, 'evening'), key='evening-receipt')
        daily = job_inputs(self.store, 'daily')
        self.assertEqual(1, len(daily['bundles']))
        self.finish(daily, [self.record('daily-insight')], key='daily-output')
        pending = job_inputs(self.store, 'evening')
        self.assertEqual(['daily-insight'], [r['id'] for b in pending['bundles'] for r in b['records']])

    def test_source_hash_changes_and_project_activity_receipts_are_inputs(self):
        source = self.vault / self.evidence[0]['path']
        self.store.index_sources([{'path': source.name, 'sha256': self.evidence[0]['sha256']}], idempotency_key='source1')
        self.finish(job_inputs(self.store, 'dream'), key='initial-sources')
        self.store.index_sources([{'path': source.name, 'sha256': self.evidence[0]['sha256']}], idempotency_key='reobserved-identical')
        self.assertFalse(job_inputs(self.store, 'dream')['has_work'])
        self.add('receipt-noise', kind='receipt')
        self.assertFalse(job_inputs(self.store, 'dream')['has_work'])
        self.add('activity', kind='receipt', body=_body('A verified fictional commit was observed.', {'schema': 1, 'kind': 'project-activity', 'events': [{'commit': 'fictional'}]}))
        inputs = job_inputs(self.store, 'dream')
        self.assertEqual(['activity'], [r['id'] for b in inputs['bundles'] for r in b['records']])

    def test_unknown_history_and_rewinds_fail_without_consuming_inputs(self):
        first = self.add('one')
        second = self.add('two')
        inputs = job_inputs(self.store, 'integrity')
        with self.assertRaises(StoreError):
            finish_job(self.store, 'integrity', 'a' * 64, [], {inputs['checkpoint_id']: 0}, 'Wrong head', self.evidence, 'wrong')
        self.finish(inputs)
        current = job_inputs(self.store, 'integrity')
        with self.assertRaises(ConflictError):
            finish_job(self.store, 'integrity', first['bundle'], [], {current['checkpoint_id']: current['checkpoint_revision']}, 'Rewind', self.evidence, 'rewind')
        self.assertFalse(job_inputs(self.store, 'integrity')['has_work'])


if __name__ == '__main__':
    unittest.main()

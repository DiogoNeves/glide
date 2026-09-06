import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from glide_memory import Store, StoreError, ConflictError
from glide_memory.bridge import MemoryServer
from glide_memory.jobs import compact_job_inputs, job_input_page, finish_job


class JobPagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.vault = root / "vault"
        self.vault.mkdir()
        self.source = self.vault / "Observation.md"
        self.source.write_text("A fictional trial changed the onboarding assumption.")
        self.evidence = [{"path": self.source.name, "sha256": hashlib.sha256(self.source.read_bytes()).hexdigest(), "quote": self.source.read_text()}]
        self.store = Store.initialize(self.vault, root / "state")
        self.store.activate_writer(old_writer_stopped=True)

    def add(self, revision, body):
        p = self.store.propose([{"id": "trial", "title": "Trial", "body": body, "sources": self.evidence}],
                               expected_revisions={"trial": revision}, rationale="Synthetic trial", idempotency_key=f"trial-{revision}")
        return self.store.apply(p["proposal_id"])

    def test_large_archive_is_compact_and_pages_cover_every_reference_once(self):
        sources = []
        for n in range(130):
            path = self.vault / f"Source {n}.md"
            path.write_text(f"Fictional source {n}")
            sources.append({"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        self.store.index_sources(sources, idempotency_key="archive")
        before = self.store.export()
        inputs = compact_job_inputs(self.store, "integrity")
        bundle = inputs["bundles"][0]
        self.assertEqual(130, bundle["source_count"])
        self.assertFalse(bundle["preview_complete"])
        self.assertLess(len(json.dumps(inputs)), 5000)
        found, cursor = [], 0
        while cursor is not None:
            page = job_input_page(self.store, "integrity", bundle["bundle"], cursor, 17)
            self.assertLessEqual(len(page["results"]), 17)
            self.assertFalse(page["processing_advanced"])
            found.extend(x["source_id"] for x in page["results"])
            cursor = page["next_cursor"]
        self.assertEqual(130, len(set(found)))
        self.assertEqual(130, len(found))
        self.assertEqual(before, self.store.export())

    def test_exact_historical_record_pointer_survives_new_revision(self):
        first = self.add(0, "Large retained source interpretation. " * 5000)
        second = self.add(1, "Later interpretation.")
        inputs = MemoryServer(self.store).call_tool("glide_job_inputs", {"job_id": "dream", "batch_limit": 1})
        self.assertEqual(first["bundle"], inputs["processed_through"])
        self.assertEqual(1, inputs["pending_count"])
        self.assertLess(len(json.dumps(inputs)), 5000)
        page = MemoryServer(self.store).call_tool("glide_job_input_page", {"job_id": "dream", "bundle": first["bundle"]})
        ref = page["results"][0]
        original = self.store.get(**ref["get_args"])
        self.assertEqual(1, original["revision"])
        self.assertTrue(original["body"].startswith("Large retained"))
        receipt = finish_job(self.store, "dream", inputs["processed_through"], [], {inputs["checkpoint_id"]: 0}, "Reviewed the first immutable input", self.evidence, "finish-first")
        self.assertTrue(receipt["committed"])
        with self.assertRaises(ConflictError):
            job_input_page(self.store, "dream", first["bundle"])
        self.assertEqual(second["bundle"], compact_job_inputs(self.store, "dream")["processed_through"])

    def test_invalid_cursor_limit_job_and_bundle_do_not_advance(self):
        receipt = self.add(0, "A useful interpretation.")
        before = self.store.export()
        for kwargs in ({"cursor": -1}, {"cursor": True}, {"cursor": 2}, {"limit": 0}, {"limit": 51}, {"limit": True}):
            with self.assertRaises(StoreError):
                job_input_page(self.store, "daily", receipt["bundle"], **kwargs)
        with self.assertRaises(StoreError):
            job_input_page(self.store, "unknown", receipt["bundle"])
        with self.assertRaises(ConflictError):
            job_input_page(self.store, "daily", "missing")
        self.assertEqual(before, self.store.export())


if __name__ == "__main__":
    unittest.main()

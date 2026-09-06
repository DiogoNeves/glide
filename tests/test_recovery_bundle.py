import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("recovery_bundle", Path(__file__).parents[1] / "tools/recovery_bundle.py")
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "config.json"
        self.source.write_text('{"writer_active":true}')
        self.policy = {"schema": 1, "instance_id": "synthetic", "export_root": str(self.root / "exports"),
                       "files": [{"name": "instance/config.json", "source": str(self.source)}]}

    def test_immutable_versions_and_idempotency(self):
        first = r.export(self.policy)
        self.assertFalse(r.export(self.policy)["created"])
        self.source.write_text('{"writer_active":false}')
        second = r.export(self.policy)
        self.assertNotEqual(first["bundle"], second["bundle"])
        self.assertEqual(json.loads((Path(first["bundle"]) / "instance/config.json").read_text()), {"writer_active": True})
        self.assertTrue(r.verify(first["bundle"])["verified"])

    def test_inspection_is_read_only_and_not_backup_success(self):
        result = r.inspect(self.policy)
        self.assertEqual(result["off_machine_backup"]["status"], "pending")
        self.assertFalse((self.root / "exports").exists())
        self.assertEqual(self.source.read_text(), '{"writer_active":true}')

    def test_detect_tampering(self):
        bundle = Path(r.export(self.policy)["bundle"])
        (bundle / "instance/config.json").write_text("changed")
        with self.assertRaises(r.RecoveryError): r.verify(str(bundle))

    def test_missing_source_does_not_publish(self):
        self.source.unlink()
        with self.assertRaises(r.RecoveryError): r.export(self.policy)
        self.assertFalse((self.root / "exports").exists())

    def test_symlink_source_and_output_rejected(self):
        link = self.root / "linked"
        link.symlink_to(self.source)
        self.policy["files"][0]["source"] = str(link)
        with self.assertRaises(r.RecoveryError): r.export(self.policy)
        self.policy["files"][0]["source"] = str(self.source)
        d = self.root / "dir"; d.mkdir()
        out = self.root / "out"; out.symlink_to(d)
        self.policy["export_root"] = str(out)
        with self.assertRaises(r.RecoveryError): r.export(self.policy)

    def test_traversal_and_duplicate_names(self):
        p = self.root / "policy.json"
        for name in ("../escape", "/absolute", "manifest.json", "RESTORE.md"):
            self.policy["files"][0]["name"] = name
            p.write_text(json.dumps(self.policy))
            with self.assertRaises(r.RecoveryError): r.load_policy(str(p))
        self.policy["files"] *= 2
        p.write_text(json.dumps(self.policy))
        with self.assertRaises(r.RecoveryError): r.load_policy(str(p))

    def test_database_and_secret_tripwires(self):
        db = self.root / "index.sqlite3"; db.write_text("text")
        with self.assertRaises(r.RecoveryError): r.admitted_bytes({"source": str(db)})
        self.source.write_text('{\n"access_token": "synthetic-token"\n}')
        with self.assertRaises(r.RecoveryError): r.export(self.policy)

    def test_extra_file_and_symlink_tampering(self):
        bundle = Path(r.export(self.policy)["bundle"])
        (bundle / "extra").write_text("unexpected")
        with self.assertRaises(r.RecoveryError): r.verify(str(bundle))
        (bundle / "extra").unlink()
        (bundle / "instance/config.json").unlink()
        (bundle / "instance/config.json").symlink_to(self.source)
        with self.assertRaises(r.RecoveryError): r.verify(str(bundle))


if __name__ == "__main__": unittest.main()

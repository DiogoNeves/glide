import importlib.util
import json
import shutil
from pathlib import Path
import tempfile
import unittest

from glide_memory import Store

spec = importlib.util.spec_from_file_location('glide_installer', Path(__file__).parents[1] / 'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='glide-install-', dir='/private/tmp' if Path('/private/tmp').is_dir() else None)
        self.root = Path(self.temporary.name)
        self.vault = self.root / 'vault'
        self.vault.mkdir()
        self.home = self.root / 'local'
        self.source = Path(__file__).parents[1]

    def tearDown(self):
        self.temporary.cleanup()

    def install(self, **kwargs):
        return installer.install(self.source, self.home, self.vault, **kwargs)

    def test_repeated_install_is_pinned_and_writer_stays_disabled(self):
        first = self.install()
        second = self.install()
        self.assertEqual(first['runtime'], second['runtime'])
        self.assertEqual('local-content-pinned-build', first['release_status'])
        self.assertFalse(Store.from_config(first['config']).config['writer_active'])
        self.assertNotIn(str(self.vault), first['runtime'])
        self.assertFalse((self.home / 'instances/personal/installation-history').exists())

    def test_knowledge_settings_default_manual_and_upgrade_omission_preserves(self):
        result = self.install(adapter='markdown', store_path='Glide HQ/Memory')
        config = json.loads(Path(result['config']).read_text())
        self.assertEqual('manual', config['knowledge_review'])
        self.assertEqual('text', config['review_ui'])
        self.assertEqual([], config['automatic_source_prefixes'])
        self.install(adapter='markdown', store_path='Glide HQ/Memory', knowledge_review='automatic', review_ui='interactive', automatic_source_prefixes=['Inbox/'])
        self.install(adapter='markdown', store_path='Glide HQ/Memory')
        config = json.loads(Path(result['config']).read_text())
        self.assertEqual('automatic', config['knowledge_review'])
        self.assertEqual('interactive', config['review_ui'])
        self.assertEqual(['Inbox/'], config['automatic_source_prefixes'])
        self.assertFalse(config['writer_active'])

    def test_legacy_upgrade_preserves_absent_knowledge_policy(self):
        result = self.install()
        path = Path(result['config'])
        config = json.loads(path.read_text())
        for key in ('knowledge_review', 'review_ui', 'automatic_source_prefixes'):
            config.pop(key)
        path.write_text(json.dumps(config))
        before = path.read_bytes()
        self.install()
        self.assertEqual(before, path.read_bytes())
        self.install(review_ui='interactive')
        updated = json.loads(path.read_text())
        self.assertEqual('interactive', updated['review_ui'])
        self.assertNotIn('knowledge_review', updated)
        self.assertNotIn('automatic_source_prefixes', updated)
        self.install(knowledge_review='manual')
        updated = json.loads(path.read_text())
        self.assertEqual('manual', updated['knowledge_review'])
        self.assertEqual('interactive', updated['review_ui'])
        self.assertFalse(updated['writer_active'])

    def test_automatic_knowledge_requires_scope_before_any_install_write(self):
        with self.assertRaisesRegex(ValueError, 'source prefix'):
            self.install(knowledge_review='automatic')
        self.assertFalse(self.home.exists())
        self.assertFalse((self.vault/'Agent HQ').exists())
        for prefix in ('../other', '/absolute', '.codex/', 'Inbox/../../other', '.', 'Inbox/.', 'Inbox//Notes', 'Inbox//'):
            with self.assertRaises(ValueError):
                self.install(knowledge_review='automatic', automatic_source_prefixes=[prefix])
        self.assertFalse(self.home.exists())

    def test_all_packaged_helpers_are_installed_outside_vault(self):
        result = self.install()
        for name in ('export_recent_notes', 'sync_voice_memos', 'codex_day_context'):
            relative = 'glide_memory/helpers/' + name + '.py'
            installed = Path(result['runtime']) / relative
            self.assertEqual((self.source/relative).read_bytes(), installed.read_bytes())
            self.assertIn(relative, result['manifest'])

    def test_existing_config_validation_precedes_manifest_mutation(self):
        result = self.install()
        installation = Path(result['installation'])
        original = installation.read_bytes()
        with self.assertRaises(ValueError):
            self.install(store_path='Other Memory')
        with self.assertRaises(ValueError):
            self.install(adapter='markdown')
        self.assertEqual(original, installation.read_bytes())
        self.assertFalse((installation.parent / 'installation-history').exists())
        self.assertFalse((self.vault / 'Other Memory').exists())

    def test_runtime_tampering_is_not_overwritten(self):
        result = self.install()
        code = Path(result['runtime']) / 'glide_memory/__init__.py'
        code.write_text('unexpected edit\n')
        with self.assertRaises(ValueError):
            self.install()
        self.assertEqual('unexpected edit\n', code.read_text())

    def test_packaged_manifest_and_expected_build_are_verified_before_writes(self):
        package = json.loads((self.source / 'package-manifest.json').read_text())
        with self.assertRaisesRegex(ValueError, 'compatibility pin'):
            self.install(expected_build='0' * 12)
        self.assertFalse(self.home.exists())
        self.assertFalse((self.vault / 'Agent HQ').exists())
        result = self.install(expected_build=package['build'])
        self.assertTrue(result['package_manifest_verified'])
        self.assertEqual(package['build'], result['build'])

    def test_altered_package_source_or_manifest_fails_without_state_changes(self):
        copied = self.root / 'copied-package'
        shutil.copytree(self.source / 'glide_memory', copied / 'glide_memory', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        shutil.copy2(self.source / 'package-manifest.json', copied / 'package-manifest.json')
        module = copied / 'glide_memory/__init__.py'
        original = module.read_bytes()
        module.write_bytes(original + b'\n# An unauthorized package edit.\n')
        with self.assertRaisesRegex(ValueError, 'Packaged runtime manifest'):
            installer.install(copied, self.home, self.vault)
        self.assertFalse(self.home.exists())
        self.assertFalse((self.vault / 'Agent HQ').exists())
        module.write_bytes(original)
        package = json.loads((copied / 'package-manifest.json').read_text())
        package['version'] = '9.9.9'
        (copied / 'package-manifest.json').write_text(json.dumps(package))
        with self.assertRaisesRegex(ValueError, 'Packaged runtime manifest'):
            installer.install(copied, self.home, self.vault)
        self.assertFalse(self.home.exists())

    def test_unsafe_local_paths_never_initialize(self):
        for home in (self.vault / 'runtime', self.root):
            with self.assertRaises(ValueError):
                installer.install(self.source, home, self.vault)
        with self.assertRaises(ValueError):
            self.install(state_name='../bad')
        with self.assertRaises(ValueError):
            self.install(store_path='../bad')
        symlink = self.root / 'linked'
        symlink.symlink_to(self.home)
        with self.assertRaises(ValueError):
            installer.install(self.source, symlink, self.vault)
        self.assertFalse(self.home.exists())
        self.assertFalse((self.vault / 'Agent HQ').exists())


if __name__ == '__main__':
    unittest.main()

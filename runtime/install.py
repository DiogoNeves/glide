#!/usr/bin/env python3
"""Install a content-pinned local build; never place executable state in a vault.

This does not claim that an unpublished build is a published upstream release.
Instance compatibility is checked before changing an existing installation record.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile


def safe_path(value):
    path = Path(os.path.abspath(os.path.expanduser(str(value))))
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink():
            raise ValueError(f'Symlink paths are not allowed: {ancestor}')
    return path


def digest(path):
    return hashlib.sha256(safe_path(path).read_bytes()).hexdigest()


def runtime_manifest(source):
    source = safe_path(source)
    result = {}
    for path in sorted(p for p in (source / 'glide_memory').rglob('*') if p.is_file() and p.suffix in {'.py', '.html'}):
        safe_path(path)
        result[path.relative_to(source).as_posix()] = digest(path)
    return result


def install(source, home, vault, state_name='personal', store_path='Agent HQ/Memory', adapter='obsidian', *, expected_build=None, knowledge_review=None, review_ui=None, automatic_source_prefixes=None):
    source, home, vault = (safe_path(p) for p in (source, home, vault))
    if home.is_relative_to(vault) or vault.is_relative_to(home):
        raise ValueError('Runtime and state must be physically separate from the vault')
    if not vault.is_dir():
        raise ValueError('Vault must already exist')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', state_name):
        raise ValueError('Invalid instance name')
    if adapter not in {'obsidian', 'markdown'}:
        raise ValueError('Unknown adapter')
    if knowledge_review not in {None, 'manual', 'automatic'} or review_ui not in {None, 'text', 'interactive'}:
        raise ValueError('Invalid knowledge review or review UI setting')
    if automatic_source_prefixes is not None:
        if not isinstance(automatic_source_prefixes, list):
            raise ValueError('Automatic source prefixes must be a list')
        for prefix in automatic_source_prefixes:
            if not isinstance(prefix, str):
                raise ValueError('Automatic source prefixes must be strings')
            value = prefix[:-1] if prefix.endswith('/') else prefix
            if not value or Path(value).is_absolute() or '\\' in value or any(not part or part.startswith('.') for part in value.split('/')):
                raise ValueError('Automatic source prefixes must be explicit vault-relative paths')
            safe_path(vault / value)
        automatic_source_prefixes = list(dict.fromkeys(automatic_source_prefixes))
    relative = Path(store_path)
    if relative.is_absolute() or '..' in relative.parts or '\\' in store_path or not relative.parts:
        raise ValueError('Store path must stay inside the vault')
    store_root = safe_path(vault / relative)
    state = safe_path(home / 'instances' / state_name)
    config = safe_path(state / 'config.json')
    installation = safe_path(state / 'installation.json')
    if not (source / 'glide_memory/__init__.py').is_file():
        raise ValueError('The supplied runtime source is incomplete')
    manifest = runtime_manifest(source)
    required = {'glide_memory/__init__.py', 'glide_memory/__main__.py', 'glide_memory/store.py'}
    if not required.issubset(manifest):
        raise ValueError('Required runtime files are missing')

    # Verify packaged contents and an adapter's expected build before importing
    # any package code or writing an installation/state file.
    build = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()[:12]
    version = '0.1.0'
    if expected_build is not None and (not isinstance(expected_build, str) or not re.fullmatch(r'[a-f0-9]{12}', expected_build)):
        raise ValueError('Expected build must be a 12-character hexadecimal content pin')
    package_manifest_path = safe_path(source / 'package-manifest.json')
    packaged = package_manifest_path.exists()
    if packaged:
        try:
            package = json.loads(package_manifest_path.read_text())
        except (ValueError, OSError) as error:
            raise ValueError('Cannot read the packaged runtime manifest') from error
        expected_package = {'schema': 1, 'version': version, 'build': build, 'files': manifest}
        if package != expected_package:
            raise ValueError('Packaged runtime manifest does not match the supplied source files, version, or build')
    if expected_build is not None and build != expected_build:
        raise ValueError('Runtime build does not match the adapter compatibility pin')

    # Validate an existing instance before writing history/manifests or packages.
    # Import only this supplied source during a fresh installer process.
    sys.path.insert(0, str(source))
    from glide_memory.store import Store, StoreError, atomic_write, read_payload
    existing = None
    if config.exists():
        existing = Store.from_config(config)
        if existing.vault != vault or existing.state_dir != state or existing.store != store_root or existing.adapter != adapter:
            raise ValueError('Instance already has different vault, state, store path, or adapter settings')
        existing._load()  # Fail closed on incomplete/divergent authoritative data.
    elif (store_root / 'Store.md').exists():
        payload = read_payload(store_root / 'Store.md')
        if payload.get('schema') != 1 or payload.get('adapter') != adapter:
            raise ValueError('Existing synced store schema or adapter differs')
    elif store_root.exists() and any(store_root.iterdir()):
        raise ValueError('Refusing to initialize a nonempty unrecognized store')

    # Omitted upgrade options preserve both values and absence. In particular,
    # introducing an explicit manual policy would change established legacy jobs.
    old_config = existing.config if existing else {}
    settings = {} if existing else {
        'knowledge_review': 'manual', 'review_ui': 'text', 'automatic_source_prefixes': [],
    }
    requested = {
        'knowledge_review': knowledge_review,
        'review_ui': review_ui,
        'automatic_source_prefixes': automatic_source_prefixes,
    }
    for key, value in requested.items():
        if value is not None:
            settings[key] = value
        elif key in old_config:
            settings[key] = old_config[key]
    if settings.get('knowledge_review') == 'automatic' and not settings.get('automatic_source_prefixes'):
        raise ValueError('Automatic knowledge ingestion requires at least one explicit source prefix')

    destination = safe_path(home / 'runtime' / f'{version}-{build}')
    if destination.exists():
        if runtime_manifest(destination) != manifest:
            raise ValueError('Installed runtime differs from its manifest; refusing overwrite')
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix='.install-', dir=destination.parent))
        try:
            # Copy only manifest-listed code. No environments, secrets, caches,
            # generated data, or unlisted symlink targets can enter the package.
            for name, expected_hash in manifest.items():
                original = safe_path(source / name)
                target = temporary / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(original.read_bytes())
                if digest(target) != expected_hash:
                    raise ValueError('Runtime source changed while installing')
            os.rename(temporary, destination)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    store = existing or Store.initialize(vault, state, store_path=store_path, adapter=adapter)
    if any(store.config.get(key) != value for key, value in settings.items()):
        store.config.update(settings)
        atomic_write(config, json.dumps(store.config, indent=2) + '\n')
    record = {'runtime_version': version, 'release_status': 'local-content-pinned-build', 'build': build, 'runtime': str(destination), 'python': sys.executable, 'files': manifest, 'adapter': adapter, 'vault': str(vault), 'store_path': store_path}
    text = json.dumps(record, indent=2) + '\n'
    if installation.exists() and installation.read_text() != text:
        previous = installation.read_bytes()
        history = safe_path(state / 'installation-history')
        atomic_write(history / f'{hashlib.sha256(previous).hexdigest()}.json', previous.decode('utf-8'), immutable=True)
    atomic_write(installation, text)
    return {'runtime': str(destination), 'config': str(config), 'installation': str(installation), 'writer_activation': 'explicit handover required' if not store.config.get('writer_active') else 'existing writer state preserved', 'release_status': record['release_status'], 'package_manifest_verified': packaged, 'build': build, 'manifest': manifest}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).parent)
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--vault', type=Path, required=True)
    parser.add_argument('--instance', default='personal')
    parser.add_argument('--expected-build', help='Content build pin required by a consuming adapter compatibility manifest')
    parser.add_argument('--store-path', default='Agent HQ/Memory')
    parser.add_argument('--knowledge-review', choices=['manual', 'automatic'], default=None, help='Fresh default manual; omitted upgrades preserve the existing value or absence')
    parser.add_argument('--review-ui', choices=['text', 'interactive'], default=None, help='Fresh default text; omitted upgrades preserve the existing choice')
    parser.add_argument('--automatic-source-prefix', action='append', dest='automatic_source_prefixes', help='Explicit vault-relative source folder or file; repeatable and required for automatic knowledge ingestion')
    parser.add_argument('--adapter', choices=['obsidian', 'markdown'], default='obsidian')
    args = parser.parse_args()
    try:
        print(json.dumps(install(args.source, args.home, args.vault, args.instance, args.store_path, args.adapter, expected_build=args.expected_build, knowledge_review=args.knowledge_review, review_ui=args.review_ui, automatic_source_prefixes=args.automatic_source_prefixes), indent=2))
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(1, f'Installation stopped: {error}\n')

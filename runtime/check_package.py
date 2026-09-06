#!/usr/bin/env python3
"""Verify one distribution against its runtime content pin before release/install.

Run from either checkout. --runtime selects a supplied sibling checkout's runtime;
this verifies the content pin and never fetches, installs, or changes a live store.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def verify(runtime, compatibility):
    runtime = runtime.resolve(strict=True)
    contract = json.loads(compatibility.read_text())
    files = {}
    for path in sorted((runtime/'glide_memory').rglob('*')):
        if path.is_symlink():
            raise ValueError('Runtime must not contain symlinks')
        if path.is_file() and path.suffix in {'.py','.html'}:
            files[path.relative_to(runtime).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    build = hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()[:12]
    package = json.loads((runtime/'package-manifest.json').read_text())
    expected = {'schema':1,'version':'0.1.0','build':build,'files':files}
    if package != expected:
        raise ValueError('Runtime package manifest differs from code')
    pin = contract['optional_memory_runtime']
    if pin['build'] != build or pin['version'] != package['version'] or pin['storage_schema_versions'] != [1]:
        raise ValueError('Distribution compatibility pin differs from runtime')
    if not pin.get('expected_build_required'):
        raise ValueError('Distribution must require its runtime build pin')
    required = {'glide_memory/review.html', *('glide_memory/helpers/'+name+'.py' for name in ('export_recent_notes','sync_voice_memos','codex_day_context'))}
    if not required <= files.keys():
        raise ValueError('Runtime helpers or review asset are absent')
    adapter = 'obsidian' if contract['distribution']=='glide-obsidian' else 'markdown'
    store_path = 'Agent HQ/Memory' if adapter=='obsidian' else 'Glide HQ/Memory'
    with tempfile.TemporaryDirectory(prefix='glide-package-check-') as temp:
        root = Path(temp).resolve(); vault=root/'workspace';vault.mkdir()
        command = [sys.executable,str(runtime/'install.py'),'--source',str(runtime),'--home',str(root/'local'),'--vault',str(vault),'--adapter',adapter,'--store-path',store_path,'--expected-build',build]
        result = subprocess.run(command,capture_output=True,text=True,check=True)
        installed=json.loads(result.stdout)
        config=json.loads(Path(installed['config']).read_text())
        if config['writer_active'] or config.get('knowledge_review')!='manual' or config.get('review_ui')!='text':
            raise ValueError('Fresh install enabled authority or changed safe defaults')
        if Path(installed['runtime']).is_relative_to(vault):
            raise ValueError('Runtime installed inside the durable workspace')
        # Repeat install must remain a no-op on identity and writer authority.
        repeat=json.loads(subprocess.run(command,capture_output=True,text=True,check=True).stdout)
        if repeat['build']!=build or json.loads(Path(installed['config']).read_text())!=config:
            raise ValueError('Repeated installation changed machine identity or settings')
    return {'ok':True,'build':build,'files':len(files),'distribution':contract['distribution'],'clean_install':'passed','writer_active':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',type=Path,default=Path(__file__).parent)
    parser.add_argument('--compatibility',type=Path,default=Path(__file__).parents[1]/'compatibility.json')
    args=parser.parse_args()
    try:
        print(json.dumps(verify(args.runtime,args.compatibility),indent=2))
    except (ValueError,KeyError,OSError,subprocess.CalledProcessError) as error:
        parser.exit(1,f'Package validation failed: {error}\n')

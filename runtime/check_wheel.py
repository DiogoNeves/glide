#!/usr/bin/env python3
"""Build an isolated wheel and exercise its packaged review and native assets.

Requires local setuptools and wheel (CI installs these). No production paths or
credentials are read, and wheel construction itself uses no dependency downloads.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile


def check(runtime):
    with tempfile.TemporaryDirectory(prefix='glide-wheel-check-') as temporary:
        root=Path(temporary).resolve();source=root/'source'
        shutil.copytree(runtime/'glide_memory',source/'glide_memory',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        shutil.copy2(runtime/'pyproject.toml',source/'pyproject.toml')
        output=root/'wheels';output.mkdir()
        env={**os.environ,'PIP_DISABLE_PIP_VERSION_CHECK':'1','PIP_NO_INDEX':'1'}
        subprocess.run([sys.executable,'-m','pip','wheel',str(source),'--no-deps','--no-build-isolation','--no-cache-dir','--wheel-dir',str(output)],env=env,capture_output=True,text=True,check=True)
        wheel=next(output.glob('*.whl'))
        installed=root/'installed';installed.mkdir()
        with zipfile.ZipFile(wheel) as package:
            if 'glide_memory/review.html' not in package.namelist():
                raise AssertionError('Wheel omitted the review template')
            package.extractall(installed)
        smoke='''from pathlib import Path
from glide_memory import Store
from glide_memory.review import render_review
from glide_memory.helpers import export_recent_notes, sync_voice_memos, codex_day_context
import tempfile, hashlib
with tempfile.TemporaryDirectory() as temp:
    root=Path(temp).resolve();vault=root/'vault';vault.mkdir()
    store=Store.initialize(vault,root/'state',adapter='markdown',store_path='Glide HQ/Memory')
    store.config['review_ui']='interactive'
    store.activate_writer(old_writer_stopped=True)
    original=vault/'source.md';original.write_text('Synthetic packaging check.')
    evidence={'path':'source.md','sha256':hashlib.sha256(original.read_bytes()).hexdigest(),'quote':'Synthetic packaging check.','locator':'line 1'}
    proposal=store.propose([{'id':'knowledge:wheel','title':'Wheel check','kind':'knowledge','origin':'ai','status':'active','body':'Synthetic packaging check.','sources':[evidence]}],expected_revisions={'knowledge:wheel':0},idempotency_key='wheel-check',rationale='Verify installed package')
    rendered=render_review(store,proposal['proposal_id'])
    assert isinstance(rendered,str) and 'Wheel check' in rendered
print('Installed wheel review and native-helper imports passed')
'''
        result=subprocess.run([sys.executable,'-c',smoke],cwd=root,env={**env,'PYTHONPATH':str(installed)},capture_output=True,text=True,check=True)
        print(result.stdout.strip())


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',type=Path,default=Path(__file__).parent)
    args=parser.parse_args()
    try:
        check(args.runtime.resolve(strict=True))
    except subprocess.CalledProcessError as error:
        parser.exit(1,'Wheel verification failed:\n'+(error.stdout or '')+(error.stderr or ''))

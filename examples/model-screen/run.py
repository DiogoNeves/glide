#!/usr/bin/env python3
"""Run an explicitly selected, billed/allowance-using synthetic Codex screen."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

EXPECTED = {
    '1': ('optional_idea', 'optional_only', {'E1', 'E2'}),
    '2': ('approval_sent_filing_unconfirmed', 'wait_for_filing_evidence', {'E3', 'E4'}),
    '3': ('onboarding_assumption_weakened', 'test_onboarding_cost', {'E5', 'E6'}),
    '4': ('one_independent_source', 'retain_provenance', {'E7'}),
    '5': ('context_change', 'preserve_dated_views', {'E10', 'E11'}),
    '6': ('coverage_unknown', 'retain_cursor_report_failure', {'E12'}),
    '7': ('ai_authored_user_reviewed', 'retain_origin', {'E13'}),
    '8': ('one_uncovered_commit', 'record_only_uncovered_evidence', {'E14'}),
}
EVIDENCE_IDS = {'E' + str(i) for i in range(1, 16)}
USAGE_KEYS = {'input_tokens', 'cached_input_tokens', 'cache_write_input_tokens', 'output_tokens', 'reasoning_output_tokens'}


def evaluate(data):
    cases = data.get('cases') if isinstance(data, dict) else None
    if not isinstance(cases, list) or len(cases) != len(EXPECTED):
        raise ValueError('Expected exactly eight cases')
    if any(not isinstance(case, dict) or not isinstance(case.get('id'), str) for case in cases):
        raise ValueError('Each case needs a string ID')
    ids = [case['id'] for case in cases]
    if len(set(ids)) != len(ids) or set(ids) != set(EXPECTED):
        raise ValueError('Case IDs must be exactly 1 through 8 without duplicates')
    indexed = {case['id']: case for case in cases}
    checks = []
    for case_id, expected in EXPECTED.items():
        actual = indexed[case_id]
        evidence = actual.get('evidence_ids')
        if not isinstance(evidence, list) or any(not isinstance(item, str) for item in evidence):
            raise ValueError('Evidence IDs must be strings in a list')
        checks.append({
            'id': case_id,
            'decision_correct': actual.get('classification') == expected[0] and actual.get('action') == expected[1],
            'required_evidence_present': expected[2].issubset(evidence),
            'evidence_ids_valid': len(evidence) == len(set(evidence)) and set(evidence).issubset(EVIDENCE_IDS),
        })
    return {'cases': checks, 'all_pass': all(all(case[key] for key in ('decision_correct', 'required_evidence_present', 'evidence_ids_valid')) for case in checks)}


def sanitized_usage(events):
    usage = []
    for line in events.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get('type') != 'turn.completed':
            continue
        value = event.get('usage')
        if isinstance(value, dict):
            usage.append({key: count for key, count in value.items() if key in USAGE_KEYS and isinstance(count, int) and not isinstance(count, bool) and count >= 0})
    return usage


def run_once(executable, model, effort, directory):
    source = Path(__file__).parent
    message = directory / 'answer.json'
    prompt = (source / 'prompt.txt').read_text() + '\nReturn exactly eight cases with string IDs "1" through "8", each once.\n'
    argv = [str(executable), 'exec', '--ignore-user-config', '--ignore-rules', '--ephemeral', '--skip-git-repo-check', '--sandbox', 'read-only', '-C', str(directory), '--model', model, '-c', f'model_reasoning_effort="{effort}"', '-c', 'features.apps=false', '-c', 'mcp_servers={}', '-c', 'plugins={}', '--output-schema', str(source / 'schema.json'), '--output-last-message', str(message), '--json', '-']
    started = time.monotonic()
    result = {'model': model, 'effort': effort, 'all_pass': False}
    try:
        process = subprocess.run(argv, input=prompt, text=True, capture_output=True, timeout=240, check=False)
        result.update(exit_code=process.returncode, elapsed_seconds=round(time.monotonic() - started, 2), usage=sanitized_usage(process.stdout))
        if process.returncode == 0:
            result.update(evaluate(json.loads(message.read_text())))
        else:
            result['error'] = 'Codex did not finish successfully; check binary compatibility, account access and selected model. Raw stderr was not retained.'
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        result.update(error=type(error).__name__, elapsed_seconds=round(time.monotonic() - started, 2))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True)
    parser.add_argument('--effort', choices=['low', 'medium', 'high', 'xhigh', 'max', 'ultra'], default='high')
    parser.add_argument('--codex', default=shutil.which('codex'))
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--repeat', type=int, choices=range(1, 6), default=1)
    parser.add_argument('--allow-model-usage', action='store_true')
    args = parser.parse_args(argv)
    if not args.allow_model_usage:
        parser.error('Explicit --allow-model-usage is required; this consumes model allowance or billing')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]*', args.model) or not args.codex:
        parser.error('Select an available model and a compatible Codex executable')
    output = args.output.expanduser().resolve()
    repository = Path(__file__).resolve().parents[2]
    if output.is_relative_to(repository) or repository.is_relative_to(output):
        parser.error('Use a private output directory outside the source repository')
    if output.exists():
        parser.error('Output directory already exists; choose a new run directory')
    executable = Path(args.codex).expanduser().resolve(strict=True)
    output.mkdir(parents=True, mode=0o700)
    results = []
    for number in range(args.repeat):
        with tempfile.TemporaryDirectory(prefix='model-screen-', dir=output) as name:
            result = run_once(executable, args.model, args.effort, Path(name))
        results.append({'repeat': number + 1, **result})
        (output / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    print(json.dumps(results, indent=2))
    return 0 if all(row['all_pass'] for row in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())

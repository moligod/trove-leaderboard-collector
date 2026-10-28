#!/usr/bin/env python3
"""Compile the modified class into a user-supplied matching stock game SWF."""
import argparse
import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_STOCK_SHA256 = '5e4bc666e3552c16f1317f58ea0d3d56a1f2fe789588ca59e8b55e2e5c35e948'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ffdec', required=True, type=Path, help='Path to ffdec-cli executable')
    parser.add_argument('--original-swf', required=True, type=Path, help='Game-owned stock leaderboard.swf')
    parser.add_argument('--output', required=True, type=Path, help='New output path; must not already exist')
    args = parser.parse_args()
    original = args.original_swf.resolve(strict=True)
    executable = args.ffdec.resolve(strict=True)
    output = args.output.resolve()
    if output.exists():
        parser.error('Output already exists; choose a new path')
    if hashlib.sha256(original.read_bytes()).hexdigest() != EXPECTED_STOCK_SHA256:
        parser.error('Stock SWF hash does not match the supported game version; do not compile against it')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='gamehub-mod-') as tmp:
        scripts = Path(tmp) / 'scripts'
        scripts.mkdir()
        shutil.copyfile(ROOT / 'mod' / 'Leaderboard.as', scripts / 'Leaderboard.as')
        candidate = Path(tmp) / 'candidate.swf'
        result = subprocess.run([str(executable), '-onerror', 'abort', '-importScript', str(original), str(candidate), str(scripts)])
        if result.returncode or not candidate.is_file() or candidate.read_bytes()[:3] not in (b'CWS', b'FWS', b'ZWS'):
            raise SystemExit('FFDec did not successfully generate a valid SWF')
        with output.open('xb') as out:
            out.write(candidate.read_bytes())
    print(f'Compiled candidate: {output}. Real-game validation is still required.')


if __name__ == '__main__': main()

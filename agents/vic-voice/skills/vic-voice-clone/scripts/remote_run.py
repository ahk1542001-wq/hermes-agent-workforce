"""Owned Colab subprocess supervisor. No allocation, upload or credentials."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import zipfile


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', required=True)
    p.add_argument('--deadline', type=int, required=True)
    a = p.parse_args()
    root = Path(a.root).resolve()
    state_path = root / 'remote-status.json'
    binding = json.loads((root / 'binding.json').read_text())
    def save(status, **extra):
        tmp = state_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(dict(status=status, binding=binding, **extra)))
        tmp.replace(state_path)
    if state_path.exists():
        previous = json.loads(state_path.read_text())
        if previous['binding'] != binding:
            raise ValueError('Remote binding mismatch')
        # A rerun is never a resume. Inspect/download partial output first.
        raise ValueError('Remote execution already recorded; do not replay')
    save('STARTING', pid=os.getpid())
    cmd = [sys.executable, '-u', str(root / 'synthesize.py'), '--chunks',
           str(root / 'chunks.json'), '--reference', str(root / 'reference.m4a'),
           '--output', str(root / 'raw')]
    started = time.monotonic()
    code = None
    with (root / 'inference.log').open('x') as log:
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                                start_new_session=True)
        save('RUNNING', pid=os.getpid(), child_pid=proc.pid)
        try:
            code = proc.wait(timeout=a.deadline)
            status = 'GENERATED' if code == 0 else 'FAILED'
        except subprocess.TimeoutExpired:
            import signal
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            status = 'REMOTE_DEADLINE'
        save(status, returncode=code, elapsed_s=time.monotonic()-started)
    # Exact relative names, no arbitrary files or symlinks in this archive.
    with zipfile.ZipFile(root / 'result.zip', 'x', zipfile.ZIP_DEFLATED) as z:
        for f in [state_path, root / 'binding.json', root / 'inference.log']:
            z.write(f, f.name)
        raw = root / 'raw'
        if raw.exists():
            for f in raw.iterdir():
                if f.is_file() and not f.is_symlink() and (f.name == 'generation.json' or f.suffix == '.wav'):
                    z.write(f, 'raw/' + f.name)
    print(json.dumps({'status': status, 'returncode': code}), flush=True)
    if status != 'GENERATED':
        raise SystemExit(1)


if __name__ == '__main__':
    main()

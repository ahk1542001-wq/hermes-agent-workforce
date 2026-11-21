#!/usr/bin/env python3
"""Run offline Creator/Voice regression checks and scan the exact release artifact."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
# Preserve the release's public commit-identity boundary.
identities = subprocess.run(['git', 'log', '--format=%ae%x00%ce'], cwd=ROOT,
                            capture_output=True, text=True, check=True).stdout
for line in identities.splitlines():
    author, committer = line.lower().split('\0')
    assert author.endswith(('@users.noreply.github.com', '@example.com'))
    assert committer.split('@') == ['noreply', 'github.com'] or committer.endswith(
        ('@users.noreply.github.com', '@example.com'))
def run(*args):
    subprocess.run([sys.executable, '-B', *args], cwd=ROOT, env=env, check=True)

for package in ['vic-creator', 'vic-voice']:
    for file in (ROOT / 'agents' / package).rglob('*.py'):
        compile(file.read_text(), file.name, 'exec')
run('-m', 'unittest', 'discover', '-s', 'agents/vic-voice/skills/vic-voice-clone/scripts', '-p', 'test_driver.py', '-v')
run('-m', 'unittest', 'discover', '-s', 'agents/vic-creator/skills/vic-video/tests', '-v')
run('-m', 'unittest', 'discover', '-s', 'agents/vic-creator/skills/vic-video/resources/short/scripts', '-p', 'test_presenter_layout.py', '-v')
spec = importlib.util.spec_from_file_location('installer', ROOT / 'scripts/install_video_profiles.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
    profiles = Path(tmp) / 'profiles'
    module.install(profiles, Path(tmp) / 'runtimes')
    assert not profiles.exists(), 'Dry run changed disk'
    module.install(profiles, Path(tmp) / 'runtimes', True)
    installed = profiles / 'vic-creator/skills/vic-video/SKILL.md'
    before = installed.read_bytes()
    assert str(profiles / 'vic-voice/skills/vic-voice-clone/SKILL.md') in installed.read_text()
    try:
        module.install(profiles, Path(tmp) / 'runtimes', True)
    except ValueError:
        pass
    else:
        raise AssertionError('Overwrote existing profiles')
    assert installed.read_bytes() == before
    assert not any(p.name in ('config.yaml', '.env', 'auth.json') for p in profiles.rglob('*'))
    module.install(profiles, Path(tmp) / 'runtimes', True, ('v-vic',))
    public_skill = ROOT / 'agents/v-vic/skills/commercial-video/SKILL.md'
    commercial_skill = profiles / 'v-vic/skills/commercial-video/SKILL.md'
    assert commercial_skill.read_bytes() == public_skill.read_bytes()
    subprocess.run(
        ['sh', 'agents/v-vic/examples/render-example.sh', str(Path(tmp) / 'commercial-demo')],
        cwd=ROOT, check=True,
    )
    artifact = Path(tmp) / 'artifact'
    run('scripts/build_release.py', str(ROOT), str(artifact))
    run('scripts/verify_public_boundary.py', str(artifact), '--manifest', str(ROOT / 'release-manifest.json'))
print('PASS: 29 regression tests; profile dry-run/install/no-overwrite/voice-link checks; commercial install and synthetic export; exact release public-boundary scan. No live model, Colab or GPU calls.')

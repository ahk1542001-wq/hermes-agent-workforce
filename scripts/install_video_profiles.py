#!/usr/bin/env python3
"""Copy public video templates to fresh profile directories; no auth/network/setup."""
import argparse
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]

PROFILES = ('vic-creator', 'vic-voice', 'v-vic')


def install(profiles, runtimes, apply=False, names=PROFILES[:2]):
    profiles, runtimes = Path(profiles).resolve(), Path(runtimes).resolve()
    if profiles == ROOT or ROOT in profiles.parents:
        raise ValueError('Profiles must live outside the public checkout')
    if not names or any(name not in PROFILES for name in names) or len(set(names)) != len(names):
        raise ValueError('Select distinct known profiles')
    destinations = [profiles / name for name in names]
    if any(p.exists() or p.is_symlink() for p in destinations):
        raise ValueError('Refusing existing profile destinations; choose a fresh root')
    print('\n'.join(str(p) for p in destinations))
    if not apply:
        print('Dry run only; use --apply after reviewing destinations')
        return
    # Preflight all destinations before creating any.
    for target in destinations:
        source = ROOT / 'agents' / target.name
        target.mkdir(parents=True, exist_ok=False)
        shutil.copyfile(source / 'hermes-profile.example/SOUL.md', target / 'SOUL.md')
        shutil.copytree(source / 'skills', target / 'skills', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        for file in target.rglob('*'):
            if file.is_file() and file.suffix in ('.md', '.py', '.js', '.ts', '.html', '.json'):
                text = file.read_text().replace('/opt/vic/profiles/', str(profiles) + '/')
                text = text.replace('/opt/vic/runtimes/', str(runtimes) + '/')
                file.write_text(text)
    print('Templates copied. Configure Hermes models/tools separately; no authentication copied.')

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--profiles-root', required=True)
    p.add_argument('--runtime-root', required=True)
    p.add_argument('--profile', choices=PROFILES, action='append', help='Select a profile; defaults to Creator and Voice')
    p.add_argument('--apply', action='store_true')
    a = p.parse_args()
    install(a.profiles_root, a.runtime_root, a.apply, a.profile or PROFILES[:2])

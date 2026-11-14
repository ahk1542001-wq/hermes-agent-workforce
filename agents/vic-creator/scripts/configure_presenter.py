#!/usr/bin/env python3
"""Register five owner-supplied PNG poses in a private installed skill."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--poses', type=Path, required=True)
p.add_argument('--manifest', type=Path, required=True, help='Private installed skill templates/presenter-assets.json')
a = p.parse_args()
root = Path(__file__).resolve().parents[3]
manifest = a.manifest.resolve()
if manifest == root or root in manifest.parents:
    raise ValueError('Keep personal asset paths outside the public repository; use an installed profile')
records = {}
for name in ['pose_stand', 'pose_present', 'pose_point', 'pose_explain', 'pose_greeting_bow']:
    file = (a.poses / (name + '.png')).resolve()
    data = file.read_bytes()
    if data[:8] != b'\x89PNG\r\n\x1a\n' or data[12:16] != b'IHDR':
        raise ValueError('Expected PNG: ' + name)
    if min(struct.unpack('>II', data[16:24])) <= 0:
        raise ValueError('Invalid PNG dimensions')
    records[name] = {'path': str(file), 'sha256': hashlib.sha256(data).hexdigest()}
if manifest.exists() and json.loads(manifest.read_text()):
    raise ValueError('Refusing to replace an existing presenter mapping')
manifest.parent.mkdir(parents=True, exist_ok=True)
manifest.write_text(json.dumps(records, indent=2) + '\n')
print('Five poses registered; inspect actual composition/identity before rendering')

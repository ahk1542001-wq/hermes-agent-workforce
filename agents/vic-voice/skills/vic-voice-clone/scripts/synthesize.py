"""Run on an already authorized GPU runtime; never provisions or uploads."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_chunks(path):
    items = json.loads(Path(path).read_text())
    if not isinstance(items, list) or not items:
        raise ValueError('Expected nonempty chunk list')
    ids = set()
    for c in items:
        cid = c['id']
        if not isinstance(cid, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', cid) or cid in ids:
            raise ValueError('Unsafe or duplicate chunk id')
        ids.add(cid)
        for key in ['spoken_text', 'visible_text']:
            if not isinstance(c[key], str) or not c[key].strip():
                raise ValueError('Missing text')
        import math
        for key in ['est_s', 'max_patches', 'pause_ms']:
            value = c[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError('Invalid chunk parameter')
        if c['est_s'] <= 0 or not isinstance(c['max_patches'], int) or c['max_patches'] <= 0:
            raise ValueError('Invalid generation budget')
    return items


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('--chunks', required=True)
    p.add_argument('--reference', required=True)
    p.add_argument('--output', required=True)
    a = p.parse_args(argv)
    items = load_chunks(a.chunks)
    ref_hash = sha(a.reference)
    binding = {'chunks_sha256': sha(a.chunks), 'reference_sha256': ref_hash,
               'model': 'openbmb/VoxCPM2', 'cfg_value': 2.0, 'inference_timesteps': 10,
               'conditioning': 'reference-only'}
    out = Path(a.output)
    ledger = out / 'generation.json'
    if out.exists():
        if not ledger.is_file():
            raise ValueError('Existing output without verified generation ledger')
        state = json.loads(ledger.read_text())
        if state['binding'] != binding:
            raise ValueError('Input/model binding mismatch; use fresh output')
    else:
        out.mkdir(parents=True)
        state = {'binding': binding, 'chunks': {}, 'status': 'IN_PROGRESS'}
    def save():
        tmp = out / 'generation.tmp'
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
        tmp.replace(ledger)
    save()
    import numpy as np
    import soundfile as sf
    model = None
    for c in items:
        cid = c['id']
        dest = out / (cid + '.wav')
        prior = state['chunks'].get(cid)
        if prior and dest.is_file() and prior['sha256'] == sha(dest):
            continue
        if dest.exists():
            raise ValueError('Unreceipted or modified chunk; inspect before recovery')
        if model is None:
            from voxcpm import VoxCPM
            model = VoxCPM.from_pretrained(binding['model'], load_denoiser=False, device='cuda')
        sr = model.tts_model.sample_rate
        wav = model.generate(text=c['spoken_text'], prompt_wav_path=None, prompt_text=None,
                             reference_wav_path=a.reference, cfg_value=2.0,
                             inference_timesteps=10, max_len=c['max_patches'],
                             normalize=False, denoise=False, retry_badcase=False)
        arr = np.asarray(wav, dtype=np.float32).reshape(-1)
        if not len(arr) or not np.isfinite(arr).all():
            raise ValueError('Invalid audio')
        duration = len(arr) / sr
        if duration < 0.4 * c['est_s'] or float(np.sqrt(np.mean(arr ** 2))) < 1e-4:
            raise ValueError('Short/silent chunk; inspect and repair, no automatic acceptance')
        sf.write(dest, arr, sr, subtype='FLOAT')
        state['chunks'][cid] = {'sha256': sha(dest), 'sample_count': len(arr),
                                'sample_rate': sr, 'duration_s': duration}
        save()
    state['status'] = 'GENERATED_PENDING_SPEECH_REVIEW'
    save()


if __name__ == '__main__':
    main()

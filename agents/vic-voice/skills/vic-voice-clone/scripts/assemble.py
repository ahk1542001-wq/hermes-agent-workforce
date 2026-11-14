"""Non-destructive local assembly; measures audio, never certifies speech quality."""
import argparse
import json
from pathlib import Path
import subprocess
from synthesize import load_chunks, sha


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('--chunks', required=True)
    p.add_argument('--raw', required=True)
    p.add_argument('--output', required=True)
    a = p.parse_args(argv)
    items = load_chunks(a.chunks)
    raw, out = Path(a.raw), Path(a.output)
    if out.exists():
        raise ValueError('Output exists; use a fresh revision')
    state = json.loads((raw / 'generation.json').read_text())
    if state['binding']['chunks_sha256'] != sha(a.chunks):
        raise ValueError('Chunk input binding mismatch')
    if state['status'] != 'GENERATED_PENDING_SPEECH_REVIEW':
        raise ValueError('Incomplete generation')
    import numpy as np
    import wave
    sr, cursor = 48000, 0
    blocks, timings = [], []
    for c in items:
        f = raw / (c['id'] + '.wav')
        r = state['chunks'][c['id']]
        if sha(f) != r['sha256']:
            raise ValueError('Raw chunk hash mismatch')
        decoded = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(f), '-f', 'f32le',
                                  '-ac', '1', '-ar', str(sr), '-'], check=True, capture_output=True)
        arr = np.frombuffer(decoded.stdout, dtype='<f4').copy()
        if not len(arr) or not np.isfinite(arr).all() or np.max(np.abs(arr)) >= 1:
            raise ValueError('Empty, invalid or clipped chunk')
        if float(np.sqrt(np.mean(arr ** 2))) < 1e-4:
            raise ValueError('Silent chunk')
        for n, head in [(min(int(sr * .01), len(arr)), True), (min(int(sr * .02), len(arr)), False)]:
            ramp = .5 * (1 - np.cos(np.linspace(0, np.pi, n)))
            if head:
                arr[:n] *= ramp
            else:
                arr[-n:] *= ramp[::-1]
        pause = round(c['pause_ms'] * sr / 1000)
        timings.append({'id': c['id'], 'visible_text': c['visible_text'],
                        'spoken_text': c['spoken_text'], 'start_sample': cursor,
                        'end_sample': cursor + len(arr), 'start_s': cursor / sr,
                        'end_s': (cursor + len(arr)) / sr, 'pause_samples': pause,
                        'raw_sha256': r['sha256']})
        blocks.extend([arr, np.zeros(pause, dtype=np.float32)])
        cursor += len(arr) + pause
    master = np.concatenate(blocks)
    # Ceiling includes the final partial 10ms block.
    env = [float(np.sqrt(np.mean(master[i:i+480] ** 2))) for i in range(0, len(master), 480)]
    maximum = max(env, default=0)
    env = [v / maximum if maximum > 1e-4 else 0 for v in env]
    out.mkdir(parents=True, exist_ok=False)
    wav = out / 'narration.wav'
    with wave.open(str(wav), 'wb') as sink:
        sink.setnchannels(1)
        sink.setsampwidth(2)
        sink.setframerate(sr)
        sink.writeframes(np.clip(np.rint(master * 32768), -32768, 32767).astype('<i2').tobytes())
    receipt = {'status': 'ASSEMBLED_PENDING_LISTENING_REVIEW', 'input_binding': state['binding'],
               'sample_rate': sr, 'sample_count': len(master), 'duration_s': len(master) / sr,
               'channels': 1, 'sha256': sha(wav), 'pause_samples': sum(x['pause_samples'] for x in timings),
               'sample_peak': float(np.max(np.abs(master))), 'loudness_lufs': None,
               'listening_coverage': 'not performed by this helper',
               'processing': '10ms head/20ms tail fades; explicit pauses; no trim/pitch/rate/EQ/normalization',
               'chunks': timings}
    (out / 'timing.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
    (out / 'audio_envelope_10ms.json').write_text(json.dumps(env))
    (out / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
    print(json.dumps({'output': str(wav), 'duration_s': len(master) / sr, 'status': receipt['status']}))


if __name__ == '__main__':
    main()

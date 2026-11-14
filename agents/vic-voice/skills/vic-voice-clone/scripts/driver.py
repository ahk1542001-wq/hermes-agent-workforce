"""Reusable job-bound Colab voice driver. Prepare is offline; run is explicit.

No bot-specific paths, model routing, speech approvals or credential handling.
Interrupted execution is recovered by download, never automatic synthesis replay.
"""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile

from deadline_runner import run as execute
from safe_diagnostics import redact
from synthesize import load_chunks, sha

HERE = Path(__file__).resolve().parent
MODEL = {'model': 'openbmb/VoxCPM2', 'cfg_value': 2.0,
         'inference_timesteps': 10, 'conditioning': 'reference-only'}
HELPERS = ['synthesize.py', 'assemble.py', 'remote_run.py', 'driver.py',
           'deadline_runner.py', 'safe_diagnostics.py']


def write(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def sessions(text):
    result = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line == '[colab] No active sessions found on server.':
            continue
        m = re.fullmatch(r'\[([\w.-]+)\]\s+(gpu-[\w-]+)\s*\|\s*Hardware:\s*([^|]+)(?:\|.*)?', line)
        if not m:
            raise ValueError('Unknown session listing; no allocation/adoption')
        result.append(dict(name=m[1], gpu_id=m[2], hardware=m[3].strip()))
    if not text.strip():
        raise ValueError('Empty session response')
    return result


def prepare(a):
    config = json.loads(Path(a.config).read_text())
    for key in ['job_id', 'session', 'chunks', 'reference', 'narration', 'authorization', 'mode']:
        if key not in config:
            raise ValueError('Missing config field: ' + key)
    for key in ['job_id', 'session']:
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,70}', config[key]):
            raise ValueError('Unsafe ' + key)
    if config['mode'] not in ['sample', 'full']:
        raise ValueError('mode must be sample or full')
    for key in ['chunks', 'reference', 'narration', 'authorization']:
        path = Path(config[key])
        if not path.is_absolute() or not path.is_file():
            raise ValueError('Expected existing absolute input path: ' + key)
    chunks = load_chunks(config['chunks'])
    normalize = lambda s: re.sub(r'\s+', '', s)
    if normalize(''.join(c['visible_text'] for c in chunks)) != normalize(Path(config['narration']).read_text()):
        raise ValueError('Chunk display text must cover the approved narration in order')
    auth = json.loads(Path(config['authorization']).read_text())
    # Explicit machine-readable attestation records actual owner permission;
    # this file cannot grant permission on its own.
    if auth.get('job_id') != config['job_id'] or auth.get('narration_sha256') != sha(config['narration']):
        raise ValueError('Authorization job/narration mismatch')
    for key in ['upload_authorized', 'synthesis_authorized', 'allocation_authorized', 'model_download_authorized']:
        if auth.get(key) is not True:
            raise ValueError('Missing scoped attestation: ' + key)
    if auth.get('reference_sha256') != sha(config['reference']) or auth.get('chunks_sha256') != sha(config['chunks']):
        raise ValueError('Authorization input hash mismatch')
    if config['mode'] == 'sample':
        ids = config.get('sample_ids', [chunks[0]['id']])
        if not ids or len(set(ids)) != len(ids) or any(cid not in {c['id'] for c in chunks} for cid in ids):
            raise ValueError('Invalid sample IDs')
        selected = [c for c in chunks if c['id'] in ids]
    else:
        selected = chunks
        validate_release(config.get('sample_review'), config)
    work = Path(a.work).resolve()
    work.mkdir(parents=True, exist_ok=False)
    # Copy code and bind its exact bytes; do not permit silently drifting helpers.
    for name in HELPERS:
        (work / name).write_bytes((HERE / name).read_bytes())
    (work / 'chunks.json').write_text(json.dumps(selected, ensure_ascii=False, indent=2))
    binding = dict(MODEL, job_id=config['job_id'], session=config['session'], mode=config['mode'],
                   chunks_sha256=sha(work/'chunks.json'), source_chunks_sha256=sha(config['chunks']),
                   reference_sha256=sha(config['reference']), narration_sha256=sha(config['narration']),
                   authorization_sha256=sha(config['authorization']),
                   helpers={n: sha(work/n) for n in HELPERS})
    binding_id = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()[:16]
    config['remote'] = '/content/vic-voice-' + config['job_id'] + '-' + binding_id
    write(work/'binding.json', binding)
    write(work/'config.json', config)
    write(work/'status.json', {'status': 'PREPARED', 'remote_launched': False})
    print(json.dumps({'work': str(work), 'status': 'PREPARED', 'chunks': len(selected)}))


def validate_release(path, config):
    if not path:
        raise ValueError('Full run requires exact sample listening-review receipt')
    r = json.loads(Path(path).read_text())
    if r.get('job_id') != config['job_id'] or r.get('reference_sha256') != sha(config['reference']):
        raise ValueError('Sample review job/reference mismatch')
    if r.get('source_chunks_sha256') != sha(config['chunks']):
        raise ValueError('Sample review source chunks mismatch')
    if r.get('coverage_accepted') is not True or r.get('likeness_accepted_by_owner') is not True:
        raise ValueError('Sample not reviewed/accepted')
    if sha(r['sample_path']) != r.get('sample_sha256') or not r.get('reviewed_by'):
        raise ValueError('Sample review must bind actual audio and reviewer')


class Driver:
    def __init__(self, work, cli):
        self.w = Path(work).resolve()
        self.c = json.loads((self.w/'config.json').read_text())
        self.b = json.loads((self.w/'binding.json').read_text())
        self.cli = str(Path(cli).resolve())
        self.state = json.loads((self.w/'status.json').read_text())
        self.verify()

    def verify(self):
        for key in ['reference', 'narration']:
            if sha(self.c[key]) != self.b[key+'_sha256']:
                raise ValueError('Changed input: ' + key)
        if sha(self.c['chunks']) != self.b['source_chunks_sha256'] or sha(self.w/'chunks.json') != self.b['chunks_sha256']:
            raise ValueError('Changed chunk inputs')
        if sha(self.c['authorization']) != self.b['authorization_sha256']:
            raise ValueError('Changed authorization')
        for n, h in self.b['helpers'].items():
            if sha(self.w/n) != h:
                raise ValueError('Changed staged helper')
        self.validate_config()
        if self.c['mode'] == 'full':
            validate_release(self.c['sample_review'], self.c)

    def validate_config(self):
        if any(self.c[k] != self.b[k] for k in ['job_id','mode','session']):
            raise ValueError('Changed staged job/mode')
        binding_id=hashlib.sha256(json.dumps(self.b,sort_keys=True).encode()).hexdigest()[:16]
        if self.c['remote'] != '/content/vic-voice-'+self.b['job_id']+'-'+binding_id:
            raise ValueError('Changed remote root')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,70}',self.c['session']):
            raise ValueError('Unsafe session')

    def log(self, value):
        value = redact(value)
        with (self.w/'driver.log').open('a') as f:
            f.write(value+'\n')
        print(value, flush=True)

    def save(self, status, **extra):
        self.state.update(status=status, **extra)
        write(self.w/'status.json', self.state)

    def call(self, *args, timeout=60):
        return execute([self.cli, '--auth', 'oauth2', *map(str,args)], timeout, self.log)

    def cell(self, code, name, timeout=60):
        p = self.w/name
        if p.exists() and p.read_text() != code:
            raise ValueError('Wrapper collision')
        p.write_text(code)
        return self.call('exec', '-s', self.c['session'], '-f', p, '--timeout', timeout, timeout=timeout+30)

    def owned(self):
        current = sessions(self.call('sessions'))
        p = self.w/'ownership.json'
        if not p.exists():
            raise ValueError('Missing ownership receipt')
        saved = json.loads(p.read_text())
        if current != [saved]:
            raise ValueError('Immutable session identity changed or foreign session present')
        return saved

    def run(self):
        if self.state['status'] != 'PREPARED':
            raise ValueError('Run already started; use recover/finish/status, never replay')
        self.call('usage')
        if sessions(self.call('sessions')):
            raise ValueError('Active session exists; refusing adoption/allocation')
        self.save('ALLOCATING')
        self.call('new', '--session', self.c['session'], '--gpu', 'T4', timeout=120)
        current = sessions(self.call('sessions'))
        if len(current) != 1 or current[0]['name'] != self.c['session'] or current[0]['hardware'] != 'T4':
            raise ValueError('Allocation identity/hardware mismatch; inspect before further action')
        write(self.w/'ownership.json', current[0])
        self.save('SETUP')
        probe = self.cell("import importlib.util\nprint('VIC_READY' if all(importlib.util.find_spec(n) for n in ['voxcpm','soundfile','librosa','numpy']) else 'VIC_MISSING')\n", 'readiness.py')
        if 'VIC_READY' not in probe:
            auth = json.loads(Path(self.c['authorization']).read_text())
            if auth.get('remote_bootstrap_authorized') is not True:
                self.stop_setup('BOOTSTRAP_PERMISSION_REQUIRED')
                raise ValueError('Missing scoped remote bootstrap permission')
            self.call('install','-s',self.c['session'],'voxcpm','soundfile','librosa','numpy',timeout=600)
        auth = json.loads(Path(self.c['authorization']).read_text())
        if auth.get('model_download_authorized') is not True:
            self.stop_setup('MODEL_DOWNLOAD_PERMISSION_REQUIRED')
            raise ValueError('Model download permission required')
        remote = self.c['remote']
        self.cell('from pathlib import Path\np=Path('+repr(remote)+')\np.mkdir(parents=True,exist_ok=False)\n', 'mkdir.py')
        for name in ['synthesize.py','remote_run.py','chunks.json','binding.json']:
            self.call('upload','-s',self.c['session'],self.w/name,remote+'/'+name,timeout=120)
        self.call('upload','-s',self.c['session'],self.c['reference'],remote+'/reference.m4a',timeout=120)
        expected = {n:sha(self.w/n) for n in ['synthesize.py','remote_run.py','chunks.json','binding.json']}
        expected['reference.m4a'] = self.b['reference_sha256']
        self.cell('from pathlib import Path\nimport hashlib\np=Path('+repr(remote)+')\nexpected='+repr(expected)+'\nassert all(hashlib.sha256((p/n).read_bytes()).hexdigest()==h for n,h in expected.items())\nprint("VIC_UPLOAD_VERIFIED")\n','verify_upload.py')
        deadline = 900 + 150 * len(load_chunks(self.w/'chunks.json'))
        self.save('EXECUTING', remote_launched=True)
        code = 'import subprocess,sys\nr=subprocess.run([sys.executable,"-u",'+repr(remote+'/remote_run.py')+',"--root",'+repr(remote)+',"--deadline",'+repr(str(deadline))+'])\nassert r.returncode==0,"Remote voice failed; recover diagnostics"\n'
        try:
            self.cell(code, 'launch.py', timeout=deadline+60)
        except Exception:
            self.save('AWAITING_REMOTE_INSPECTION')
            raise
        self.recover()

    def stop_setup(self, status):
        self.owned()
        self.call('stop','-s',self.c['session'])
        if any(s['gpu_id']==json.loads((self.w/'ownership.json').read_text())['gpu_id'] for s in sessions(self.call('sessions'))):
            raise ValueError('Setup teardown not confirmed')
        self.save(status, runtime_stopped=True)

    def recover(self):
        self.owned()
        statusfile = self.w/'remote-status-download.json'
        self.call('download','-s',self.c['session'],self.c['remote']+'/remote-status.json', statusfile,timeout=120)
        remote = json.loads(statusfile.read_text())
        if remote.get('binding') != self.b:
            raise ValueError('Remote status binding mismatch')
        if remote['status'] in ['STARTING','RUNNING']:
            self.save('AWAITING_REMOTE_INSPECTION')
            raise ValueError('Remote may still be running; no stop/retry')
        if remote['status'] not in ['GENERATED','FAILED','REMOTE_DEADLINE']:
            raise ValueError('Unknown remote status')
        archive = self.w/'result.zip'
        if archive.exists():
            raise ValueError('Archive already downloaded; use finish')
        self.call('download','-s',self.c['session'],self.c['remote']+'/result.zip',archive,timeout=180)
        self.save('DOWNLOADED')
        self.finish()

    def finish(self):
        dest = self.w/'downloaded'
        if not dest.exists():
            with zipfile.ZipFile(self.w/'result.zip') as z:
                names=z.namelist()
                allowed={'remote-status.json','binding.json','inference.log','raw/generation.json'} | {'raw/'+c['id']+'.wav' for c in load_chunks(self.w/'chunks.json')}
                if len(names)!=len(set(names)) or any(n not in allowed for n in names):
                    raise ValueError('Unexpected/unsafe archive member')
                dest.mkdir()
                z.extractall(dest)
        if json.loads((dest/'binding.json').read_text()) != self.b:
            raise ValueError('Archive binding mismatch')
        status=json.loads((dest/'remote-status.json').read_text())
        if status.get('binding') != self.b or status['status'] not in ['GENERATED','FAILED','REMOTE_DEADLINE']:
            raise ValueError('Archive terminal status mismatch')
        complete=status['status']=='GENERATED'
        if complete:
            self.verify_raw(dest/'raw')
        # Terminal subprocess receipt + safely retrieved artifacts: no live inference.
        if not self.state.get('runtime_stopped'):
            self.owned()
            self.call('stop','-s',self.c['session'])
            saved=json.loads((self.w/'ownership.json').read_text())
            if any(s['gpu_id']==saved['gpu_id'] for s in sessions(self.call('sessions'))):
                raise ValueError('Stop not confirmed')
            self.save('RETRIEVED', runtime_stopped=True)
        if not complete:
            self.save('REMOTE_FAILED_ARTIFACTS_PRESERVED')
            raise ValueError('Remote failure; inspect retrieved diagnostics, no automatic retry')
        if not (self.w/'assembled').exists():
            execute([sys.executable,str(self.w/'assemble.py'),'--chunks',str(self.w/'chunks.json'),'--raw',str(dest/'raw'),'--output',str(self.w/'assembled')],120,self.log)
        receipt=json.loads((self.w/'assembled/receipt.json').read_text())
        if sha(self.w/'assembled/narration.wav') != receipt['sha256']:
            raise ValueError('Assembled master hash mismatch')
        self.save('ASSEMBLED_PENDING_LISTENING_REVIEW', master=str(self.w/'assembled/narration.wav'),sha256=receipt['sha256'])

    def verify_raw(self, raw):
        g=json.loads((raw/'generation.json').read_text())
        expected=dict(MODEL,chunks_sha256=self.b['chunks_sha256'],reference_sha256=self.b['reference_sha256'])
        items=load_chunks(self.w/'chunks.json')
        if g.get('binding')!=expected or g.get('status')!='GENERATED_PENDING_SPEECH_REVIEW' or set(g['chunks'])!={c['id'] for c in items}:
            raise ValueError('Incomplete/mismatched generation ledger')
        for c in items:
            f=raw/(c['id']+'.wav')
            if sha(f)!=g['chunks'][c['id']]['sha256']:
                raise ValueError('WAV hash mismatch')
            execute(['ffmpeg','-v','error','-i',str(f),'-f','null','-'],60,self.log)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['prepare','run','recover','finish','status'])
    p.add_argument('--work',required=True)
    p.add_argument('--config')
    p.add_argument('--colab',default=os.environ.get('VIC_COLAB_CLI','colab'))
    a=p.parse_args()
    if a.action=='prepare':
        if not a.config: p.error('--config required for prepare')
        prepare(a);return
    import shutil
    cli=shutil.which(a.colab)
    if not cli: raise ValueError('Installed Colab CLI not found')
    w=Path(a.work).resolve()
    with (w/'driver.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        # Serialize this account's allocation/session use across bots and jobs.
        # sessions/new alone is not an atomic ownership claim.
        import tempfile
        account_lock = open(Path(tempfile.gettempdir()) / ('vic-colab-account-'+str(os.getuid())+'.lock'), 'a')
        fcntl.flock(account_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        d=Driver(w,cli)
        write(w/'process.json',{'pid':os.getpid(),'action':a.action})
        if a.action=='status': print(json.dumps(d.state,indent=2))
        else: getattr(d,a.action)()


if __name__=='__main__':
    try: main()
    except Exception as e:
        print(redact(type(e).__name__+': '+str(e)),file=sys.stderr)
        raise SystemExit(1)

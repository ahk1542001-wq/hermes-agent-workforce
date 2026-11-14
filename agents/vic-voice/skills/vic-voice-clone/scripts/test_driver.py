"""Offline regression/integration fixtures. Never imports VoxCPM or calls Colab."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import wave
import zipfile
from unittest.mock import patch
import numpy as np
import driver
from deadline_runner import run
from safe_diagnostics import redact


class FakeColab(driver.Driver):
    """Explicit test adapter; production driver has no mock-audio mode."""
    def __init__(self,*args):
        self.active=[]; self.calls=[]; self.busy=False; self.bad_archive=False
        super().__init__(*args)
    def call(self,*args,timeout=60):
        self.calls.append(args)
        if args[0]=='usage': return 'offline fixture'
        if args[0]=='sessions':
            return '[colab] No active sessions found on server.' if not self.active else '\n'.join('['+s['name']+'] '+s['gpu_id']+' | Hardware: '+s['hardware'] for s in self.active)
        if args[0]=='new':
            self.active=[dict(name=self.c['session'],gpu_id='gpu-fixture',hardware='T4')];return ''
        if args[0]=='stop':self.active=[];return ''
        if args[0] in ['upload','install']:return ''
        if args[0]=='download':
            dest=Path(args[-1])
            if str(args[-2]).endswith('remote-status.json'):
                driver.write(dest,dict(binding=self.b,status='RUNNING' if self.busy else 'GENERATED'))
            else:self.make_archive(dest)
            return ''
        raise AssertionError(args)
    def cell(self,code,name,timeout=60):
        self.calls.append(('cell',name))
        return 'VIC_READY'
    def make_archive(self,dest):
        with tempfile.TemporaryDirectory() as t:
            t=Path(t);raw=t/'raw';raw.mkdir()
            ledger=dict(binding=dict(driver.MODEL,chunks_sha256=self.b['chunks_sha256'],reference_sha256=self.b['reference_sha256']),status='GENERATED_PENDING_SPEECH_REVIEW',chunks={})
            for c in driver.load_chunks(self.w/'chunks.json'):
                f=raw/(c['id']+'.wav')
                arr=(np.sin(np.arange(4800)*.03)*3000).astype('<i2')
                with wave.open(str(f),'wb') as w:
                    w.setparams((1,2,48000,0,'NONE','not compressed'));w.writeframes(arr.tobytes())
                ledger['chunks'][c['id']]=dict(sha256=driver.sha(f),sample_count=4800,sample_rate=48000,duration_s=.1)
            driver.write(raw/'generation.json',ledger)
            with zipfile.ZipFile(dest,'w') as z:
                z.writestr('binding.json',json.dumps(self.b))
                z.writestr('remote-status.json',json.dumps(dict(binding=self.b,status='GENERATED')))
                for f in raw.iterdir():z.write(f,'raw/'+f.name)
                if self.bad_archive:z.writestr('../escape','bad')


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.chunks=self.root/'chunks.json';self.reference=self.root/'reference.m4a';self.narration=self.root/'narration.txt'
        self.reference.write_bytes(b'fixture reference - never uploaded');self.narration.write_text('one two')
        driver.write(self.chunks,[dict(id='one',spoken_text='one',visible_text='one',est_s=.1,max_patches=100,pause_ms=10),dict(id='two',spoken_text='two',visible_text='two',est_s=.1,max_patches=100,pause_ms=0)])
        self.auth=self.root/'auth.json'
        driver.write(self.auth,dict(job_id='fixture',narration_sha256=driver.sha(self.narration),chunks_sha256=driver.sha(self.chunks),reference_sha256=driver.sha(self.reference),upload_authorized=True,synthesis_authorized=True,allocation_authorized=True,model_download_authorized=True,remote_bootstrap_authorized=True))
        self.cfg=dict(job_id='fixture',session='fixture-session',mode='sample',sample_ids=['one'],chunks=str(self.chunks),reference=str(self.reference),narration=str(self.narration),authorization=str(self.auth))
        self.config=self.root/'config.json';driver.write(self.config,self.cfg)
        self.work=self.root/'work'
    def prepare(self):
        with contextlib.redirect_stdout(io.StringIO()):driver.prepare(type('Args',(),dict(config=str(self.config),work=str(self.work)))())
        return FakeColab(self.work,'/bin/true')
    def test_sample_pipeline_download_decode_assemble_stop(self):
        d=self.prepare()
        with contextlib.redirect_stdout(io.StringIO()):d.run()
        self.assertEqual(d.state['status'],'ASSEMBLED_PENDING_LISTENING_REVIEW')
        self.assertTrue(d.state['runtime_stopped']);self.assertEqual(d.active,[])
        self.assertFalse(any(c[0]=='install' for c in d.calls))
        receipt=json.loads((self.work/'assembled/receipt.json').read_text())
        self.assertEqual(receipt['sample_count'],5280)
        self.assertEqual(len(receipt['chunks']),1)
        with self.assertRaises(ValueError):d.run()
    def test_full_pipeline_and_exact_review_gate(self):
        sample=self.root/'sample.wav';sample.write_bytes(b'owner reviewed fixture')
        review=self.root/'review.json';driver.write(review,dict(job_id='fixture',reference_sha256=driver.sha(self.reference),source_chunks_sha256=driver.sha(self.chunks),sample_path=str(sample),sample_sha256=driver.sha(sample),reviewed_by='fixture owner',coverage_accepted=True,likeness_accepted_by_owner=True))
        self.cfg.update(mode='full',sample_review=str(review));driver.write(self.config,self.cfg)
        d=self.prepare()
        with contextlib.redirect_stdout(io.StringIO()):d.run()
        self.assertEqual(len(json.loads((self.work/'assembled/receipt.json').read_text())['chunks']),2)
        sample.write_bytes(b'changed')
        with self.assertRaises(ValueError):d.verify()
    def test_full_without_review_refused_before_work(self):
        self.cfg['mode']='full';driver.write(self.config,self.cfg)
        with self.assertRaises(ValueError):self.prepare()
        self.assertFalse(self.work.exists())
    def test_changed_input_refused(self):
        d=self.prepare();self.reference.write_bytes(b'changed')
        with self.assertRaises(ValueError):d.verify()
    def test_unapproved_chunk_content_refused(self):
        self.narration.write_text('a different script')
        a=json.loads(self.auth.read_text());a['narration_sha256']=driver.sha(self.narration);driver.write(self.auth,a)
        with self.assertRaises(ValueError):self.prepare()
    def test_remote_path_mutation_refused(self):
        d=self.prepare();d.c['remote']='/content/other-job'
        with self.assertRaises(ValueError):d.verify()
    def test_foreign_session_no_allocation(self):
        d=self.prepare();d.active=[dict(name='foreign',gpu_id='gpu-other',hardware='T4')]
        with self.assertRaises(ValueError):d.run()
        self.assertFalse(any(c[0] in ['new','stop','upload'] for c in d.calls))
    def test_timeout_no_stop_or_replay(self):
        d=self.prepare()
        original=d.cell
        def cell(code,name,timeout=60):
            if name=='launch.py':raise subprocess.TimeoutExpired('fixture',1)
            return original(code,name,timeout)
        d.cell=cell
        with self.assertRaises(subprocess.TimeoutExpired):d.run()
        self.assertEqual(d.state['status'],'AWAITING_REMOTE_INSPECTION')
        self.assertFalse(any(c[0]=='stop' for c in d.calls))
        d.busy=True
        with self.assertRaises(ValueError):d.recover()
        self.assertFalse(any(c[0]=='stop' for c in d.calls))
        d.busy=False
        with contextlib.redirect_stdout(io.StringIO()):d.recover()
        self.assertEqual(d.state['status'],'ASSEMBLED_PENDING_LISTENING_REVIEW')
    def test_archive_traversal_rejected(self):
        d=self.prepare();d.bad_archive=True
        with self.assertRaises(ValueError):d.run()
        self.assertFalse((self.work/'escape').exists())
    def test_unknown_session_format_rejected(self):
        with self.assertRaises(ValueError):driver.sessions('unrecognized')
        self.assertEqual(driver.sessions('[colab] No active sessions found on server.'),[])
    def test_authorization_input_binding(self):
        a=json.loads(self.auth.read_text());a['reference_sha256']='wrong';driver.write(self.auth,a)
        with self.assertRaises(ValueError):self.prepare()
    def test_missing_upload_permission(self):
        a=json.loads(self.auth.read_text());a['upload_authorized']=False;driver.write(self.auth,a)
        with self.assertRaises(ValueError):self.prepare()
    def test_silent_deadline_and_nonzero(self):
        with self.assertRaises(subprocess.TimeoutExpired):run([sys.executable,'-c','import time;time.sleep(10)'],.2,lambda x:None)
        with self.assertRaises(subprocess.CalledProcessError):run([sys.executable,'-c','raise SystemExit(42)'],2,lambda x:None)
    def test_early_output_before_child_exit(self):
        import time
        seen=[];start=time.monotonic()
        run([sys.executable,'-u','-c','import time;print("early");time.sleep(.6)'],2,lambda x:seen.append(time.monotonic()-start))
        self.assertLess(seen[0],.5)
    def test_remote_supervisor_kills_silent_worker_and_preserves_archive(self):
        remote=self.root/'remote';remote.mkdir()
        driver.write(remote/'binding.json',{'test':'isolated'})
        (remote/'synthesize.py').write_text('import time;time.sleep(10)')
        result=subprocess.run([sys.executable,str(driver.HERE/'remote_run.py'),'--root',str(remote),'--deadline','1'],capture_output=True,timeout=4)
        self.assertEqual(result.returncode,1)
        self.assertEqual(json.loads((remote/'remote-status.json').read_text())['status'],'REMOTE_DEADLINE')
        self.assertTrue((remote/'result.zip').is_file())
        second=subprocess.run([sys.executable,str(driver.HERE/'remote_run.py'),'--root',str(remote),'--deadline','1'],capture_output=True,timeout=2)
        self.assertNotEqual(second.returncode,0)
    def test_token_redaction(self):
        self.assertNotIn('PRIVATE',redact('https://x/?token=PRIVATE&k=PRIVATE Bearer PRIVATE'))


if __name__=='__main__':unittest.main()

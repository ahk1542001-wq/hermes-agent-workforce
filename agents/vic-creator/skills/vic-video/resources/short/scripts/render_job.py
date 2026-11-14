import os
#!/usr/bin/env python3
"""Retained Chromium→FFmpeg export, driven by prepared job data. One process only."""
from pathlib import Path
import argparse,json,subprocess,math,time,hashlib
from playwright.sync_api import sync_playwright
from prepare_job import verify_inputs

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def render(job,name,start,length):
    job=Path(job).resolve();m=json.loads((job/'build.json').read_text());d=m['duration_s'];source=job/'video.html';audio=(job/m['audio']).resolve()
    if sha(source)!=m['source_sha256'] or not audio.is_relative_to(job) or sha(audio)!=m['audio_sha256']:raise ValueError('Prepared source/audio changed; rebuild a fresh revision')
    verify_inputs(job,m)
    length=d-start if length is None else length
    if not (math.isfinite(start) and math.isfinite(length) and start>=0 and length>0 and start+length<=d+.001 and abs(length*30-round(length*30))<1e-6):raise ValueError('Invalid frame-aligned export interval')
    out=(job/name).resolve()
    if not out.is_relative_to(job) or out.suffix!='.mp4' or any(p.exists() or p.is_symlink() for p in [job/name,out,out.with_suffix('.receipt.json'),out.with_suffix('.ffmpeg.log')]):raise ValueError('Use a fresh job-local MP4 filename')
    frames=round(length*30);cmd=[os.environ.get("VIC_FFMPEG", "ffmpeg"),'-nostdin','-n','-hide_banner','-loglevel','error','-f','image2pipe','-vcodec','mjpeg','-r','30','-i','-','-ss',str(start),'-t',str(length),'-i',str(audio),'-map','0:v:0','-map','1:a:0','-c:v','libx264','-preset','fast','-crf','18','-vf','scale=in_range=pc:out_range=tv:in_color_matrix=bt601:out_color_matrix=bt709,format=yuv420p','-color_range','tv','-colorspace','bt709','-color_primaries','bt709','-color_trc','bt709','-c:a','aac','-ar','48000','-b:a','160k','-af',f'apad=whole_dur={length},afade=t=out:st={max(0,length-.25)}:d=0.25','-t',str(length),'-movflags','+faststart',str(out)]
    begun=time.time();errors=[]
    with sync_playwright() as p:
        b=p.chromium.launch(executable_path=os.environ.get("VIC_CHROME"),args=['--allow-file-access-from-files','--disable-gpu']);pg=b.new_page(viewport={'width':1080,'height':1920},device_scale_factor=1);pg.on('pageerror',lambda e:errors.append(str(e)));pg.goto(source.as_uri());pg.wait_for_function('isReady()',timeout=30000);pg.evaluate('document.fonts.ready');pg.evaluate('seekFrame',start);pg.screenshot(type='jpeg')
        if errors:raise RuntimeError(str(errors))
        log=out.with_suffix('.ffmpeg.log')
        with log.open('w') as f:
            proc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stderr=f)
            try:
                for n in range(frames):
                    pg.evaluate('seekFrame',start+n/30)
                    if errors:raise RuntimeError(str(errors))
                    proc.stdin.write(pg.screenshot(type='jpeg',quality=96))
                    if (n+1)%150==0:print(f'{n+1}/{frames} frames',flush=True)
                proc.stdin.close();code=proc.wait()
                if code:raise RuntimeError('FFmpeg failed: '+str(code))
            except BaseException:
                if proc.poll() is None:proc.terminate();proc.wait()
                raise
            finally:b.close()
    receipt=dict(output=out.name,sha256=sha(out),start_s=start,duration_s=length,frames=frames,exit_code=0,elapsed_s=round(time.time()-begun,2),source_sha256=m['source_sha256'],audio_sha256=m['audio_sha256'],scope='Export receipt only; full decode/content/motion/audio QA and owner acceptance separate')
    out.with_suffix('.receipt.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--job',required=True);p.add_argument('--output',required=True);p.add_argument('--start',type=float,default=0);p.add_argument('--duration',type=float);a=p.parse_args();render(a.job,a.output,a.start,a.duration)

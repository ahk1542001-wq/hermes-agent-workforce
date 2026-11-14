import os
#!/usr/bin/env python3
"""Job-local sound design, deterministic FFmpeg mix and binding verification.
No downloads/generation and no subjective listening PASS.
"""
from pathlib import Path
import argparse, hashlib, json, math, subprocess, re
FFMPEG=os.environ.get("VIC_FFMPEG", "ffmpeg")
FFPROBE=os.environ.get("VIC_FFPROBE", "ffprobe")

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def local(job,name):
    p=(job/name).resolve()
    if not p.is_relative_to(job) or not p.is_file():raise ValueError('Missing/outside job-local audio input')
    return p

def number(x,lo,hi,label):
    if type(x) not in (int,float) or not math.isfinite(x) or not lo<=x<=hi:raise ValueError('Invalid '+label)
    return x

def probe(p):
    j=json.loads(subprocess.run([FFPROBE,'-v','error','-show_streams','-show_format','-of','json',str(p)],capture_output=True,text=True,check=True).stdout)
    a=next(s for s in j['streams'] if s['codec_type']=='audio')
    return float(j['format']['duration']),a

def validate(job,plan):
    job=Path(job).resolve();p=local(job,plan);s=json.loads(p.read_text())
    duration=number(s['duration_s'],.1,3600,'duration')
    if abs(duration*30-round(duration*30))>1e-6:raise ValueError('Use frame-aligned film duration')
    dry=local(job,s['narration']);ad,_=probe(dry)
    if ad>duration+1/48000:raise ValueError('Sound plan would cut narration')
    if s.get('mode') not in ['designed','voice-only']:raise ValueError('Explicit designed/voice-only choice required')
    tracks=[]
    for kind in ['music','sfx']:
        cues=s.get(kind)
        if not isinstance(cues,list):raise ValueError('Explicit music and sfx lists required')
        if not cues and not str(s.get(kind+'_omission_reason','')).strip():raise ValueError('Explain omitted '+kind)
        if s['mode']=='voice-only' and cues:raise ValueError('Voice-only mode cannot contain music/SFX')
        for c in cues:
            if not all(isinstance(c.get(k),str) and c[k].strip() for k in ['id','purpose','source','license']):raise ValueError('Cue needs id/purpose/source/license')
            f=local(job,c['path']);at=number(c['at_s'],0,duration,'cue time');length=number(c['duration_s'],.01,duration,'cue duration')
            if at+length>duration+1/48000:raise ValueError('Cue tail outside film')
            gain=number(c['gain_db'],-80,0,'cue gain')
            fi=number(c.get('fade_in_s',min(.02,length/2)),0,length/2,'fade in');fo=number(c.get('fade_out_s',min(.1,length/2)),0,length/2,'fade out')
            loop=c.get('loop',False)
            if type(loop)!=bool or (kind=='sfx' and loop):raise ValueError('Only music can loop')
            length_available,_=probe(f)
            if not loop and length_available+1/48000<length:raise ValueError('Cue file shorter than declared segment')
            tracks.append(dict(kind=kind,path=f,id=c['id'],at=at,length=length,gain=gain,fi=fi,fo=fo,loop=loop))
    if len({c['id'] for c in tracks})!=len(tracks):raise ValueError('Duplicate cue IDs')
    lufs=number(s.get('target_lufs',-18),-30,-10,'target loudness');peak=number(s.get('true_peak_dbtp',-1.5),-6,-1,'peak ceiling')
    return p,s,dry,tracks,duration,lufs,peak

def verify_mix(job,plan,output,receipt):
    job=Path(job).resolve();p,s,dry,tracks,d,_,_=validate(job,plan)
    rec=local(job,receipt);r=json.loads(rec.read_text());out=local(job,output)
    if r.get('status')!='MIXED_PENDING_LISTENING_REVIEW' or r.get('plan_sha256')!=sha(p) or r.get('output_sha256')!=sha(out):raise ValueError('Stale/missing sound mix receipt')
    required={str(p.relative_to(job)):sha(p),str(dry.relative_to(job)):sha(dry)}
    required.update({str(c['path'].relative_to(job)):sha(c['path']) for c in tracks})
    if r.get('inputs')!=required:raise ValueError('Sound source bindings changed')
    actual,a=probe(out)
    if abs(actual-d)>1/48000+1e-6 or int(a['sample_rate'])!=48000:raise ValueError('Mix duration/sample rate mismatch')
    levels=r.get('measured',{})
    for key in ['input_i','input_tp']:
        try:v=float(levels[key])
        except (KeyError,ValueError,TypeError):raise ValueError('Missing actual measured sound levels')
        if not math.isfinite(v):raise ValueError('Invalid measured sound level')
    if float(levels['input_tp'])>r['true_peak_dbtp']+.3:raise ValueError('Mix exceeds planned peak headroom')
    return required | {str(rec.relative_to(job)):sha(rec),str(out.relative_to(job)):sha(out)}

def level(path,lufs,peak):
    r=subprocess.run([FFMPEG,'-nostdin','-hide_banner','-i',str(path),'-af',f'loudnorm=I={lufs}:TP={peak}:LRA=9:print_format=json','-f','null','-'],capture_output=True,text=True,check=True)
    blocks=re.findall(r'\{[^{}]*"input_i"[^{}]*\}',r.stderr,re.S)
    if not blocks:raise ValueError('No measured audio levels')
    j=json.loads(blocks[-1])
    for k in ['input_i','input_tp','input_lra','input_thresh','target_offset']:
        if not math.isfinite(float(j[k])):raise ValueError('Silent/invalid mix cannot be mastered')
    return j

def mix(job,plan,output):
    job=Path(job).resolve();p,s,dry,tracks,d,lufs,peak=validate(job,plan)
    out=(job/output).resolve();rec=out.with_suffix('.mix.json');pre=out.with_suffix('.premaster.wav')
    if not out.is_relative_to(job) or out.suffix!='.wav' or any(x.exists() or x.is_symlink() for x in [out,rec,pre]):raise ValueError('Use a fresh job-local WAV output')
    inputs={str(p.relative_to(job)):sha(p),str(dry.relative_to(job)):sha(dry)}
    inputs.update({str(c['path'].relative_to(job)):sha(c['path']) for c in tracks})
    args=[FFMPEG,'-nostdin','-n','-v','error','-i',str(dry)]
    for c in tracks:
        if c['loop']:args+=['-stream_loop','-1']
        args+=['-i',str(c['path'])]
    filters=[f'[0:a]aresample=48000,aformat=channel_layouts=stereo,apad,atrim=duration={d},asetpts=PTS-STARTPTS[voice]']
    names={'music':[],'sfx':[]}
    for i,c in enumerate(tracks,1):
        name=f'cue{i}';delay=round(c['at']*48000)
        filters.append(f'[{i}:a]aresample=48000,aformat=channel_layouts=stereo,atrim=duration={c["length"]},asetpts=PTS-STARTPTS,volume={c["gain"]}dB,afade=t=in:d={c["fi"]},afade=t=out:st={c["length"]-c["fo"]}:d={c["fo"]},adelay={delay}S:all=1,apad,atrim=duration={d}[{name}]')
        names[c['kind']].append('['+name+']')
    buses=['[voice]']
    if names['music']:
        filters.append(''.join(names['music'])+f'amix=inputs={len(names["music"])}:normalize=0[bgm]')
        filters.append('[voice]asplit=2[vmain][control]')
        filters.append('[bgm][control]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=250[ducked]')
        buses=['[vmain]','[ducked]']
    if names['sfx']:
        filters.append(''.join(names['sfx'])+f'amix=inputs={len(names["sfx"])}:normalize=0[effects]');buses.append('[effects]')
    filters.append(''.join(buses)+f'amix=inputs={len(buses)}:normalize=0,atrim=duration={d}[mix]')
    out.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run(args+['-filter_complex',';'.join(filters),'-map','[mix]','-ar','48000','-c:a','pcm_f32le','-t',str(d),str(pre)],capture_output=True,text=True,check=True)
    first=level(pre,lufs,peak)
    af=f'loudnorm=I={lufs}:TP={peak}:LRA=9:measured_I={first["input_i"]}:measured_TP={first["input_tp"]}:measured_LRA={first["input_lra"]}:measured_thresh={first["input_thresh"]}:offset={first["target_offset"]}:linear=true'
    subprocess.run([FFMPEG,'-nostdin','-n','-v','error','-i',str(pre),'-af',af,'-ar','48000','-c:a','pcm_s24le','-t',str(d),str(out)],capture_output=True,text=True,check=True)
    measured=level(out,lufs,peak)
    for path,h in inputs.items():
        if sha(job/path)!=h:raise ValueError('Input changed while mixing')
    r=dict(status='MIXED_PENDING_LISTENING_REVIEW',plan_sha256=sha(p),inputs=inputs,output_sha256=sha(out),duration_s=d,target_lufs=lufs,true_peak_dbtp=peak,measured=measured,cue_ids=[c['id'] for c in tracks],ducking=bool(names['music']),filters=filters,limits=['No listening or semantic sync acceptance','Source/license metadata is attribution, not legal clearance','Narration-only envelope must remain bound separately'])
    rec.write_text(json.dumps(r,ensure_ascii=False,indent=2));verify_mix(job,plan,output,str(rec.relative_to(job)));print(json.dumps({'output':str(out),'receipt':str(rec),'status':r['status']}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--job',required=True);p.add_argument('--plan',default='sound-plan.json');p.add_argument('--output',default='sound-mix.wav');a=p.parse_args();mix(a.job,a.plan,a.output)

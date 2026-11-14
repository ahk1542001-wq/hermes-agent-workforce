import os
#!/usr/bin/env python3
"""Bind fresh approved job data to the retained VIC renderer. No network or generation."""
from pathlib import Path
import argparse,json,math,hashlib,subprocess,re,shutil

from visual_contract import validate_plan
from sound_mix import verify_mix
ROOT=Path(__file__).resolve().parents[1]
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def verify_inputs(job,m):
    for group in ['inputs','assets']:
        for key,rec in m[group].items():
            p=(job/rec['path']).resolve()
            if not p.is_relative_to(job) or not p.is_file() or digest(p)!=rec['sha256']:raise ValueError('Prepared input changed: '+key)
def validate_presenter(shot, sources):
    """Validate per-shot image staging; glyph collision is checked in browser QA."""
    if type(shot.get('hidePresenter',False)) is not bool:raise ValueError('hidePresenter must be boolean')
    layout=shot.get('presenter',{})
    if not isinstance(layout,dict) or set(layout)-{'x','y','width'}:raise ValueError('presenter accepts x/y/width only')
    values={**{'x':28,'y':1578,'width':315},**layout}
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in values.values()):raise ValueError('Presenter layout must be finite numbers')
    x,y,w=(values[k] for k in ['x','y','width'])
    if w<=0 or x<0 or y<0:raise ValueError('Invalid presenter position/width')
    if shot.get('hidePresenter'):return
    import struct
    with Path(sources[shot.get('pose','pose_present')]['path']).open('rb') as f:header=f.read(24)
    if header[:8]!=b'\x89PNG\r\n\x1a\n' or header[12:16]!=b'IHDR':raise ValueError('Retained presenter must be a measured PNG')
    iw,ih=struct.unpack('>II',header[16:24]);height=w*ih/iw
    if x+w>1080 or y+height>1920:raise ValueError('Presenter extends outside canvas; recompose this shot')

def prepare(job):
    job=Path(job).resolve();spec=json.loads((job/'job.json').read_text());target=job/'video.html'
    if any((job/n).exists() or (job/n).is_symlink() for n in ['video.html','build.json','captions.json','shots.json','_vic_presenter']):raise ValueError('Prepared output exists; preserve it and use an owned fresh revision')
    def file(key):
        p=(job/spec[key]).resolve()
        if not p.is_relative_to(job) or not p.is_file():raise ValueError(f'{key}: input must be an existing job-local file')
        return p
    audio=file('audio');envfile=file('envelope');chunkfile=file('chunks');planfile,plan,contract=validate_plan(job,spec)
    if not spec.get('sound_plan') or not spec.get('sound_receipt'):raise ValueError('New video preparation requires explicit sound plan and verified mix receipt')
    sound_bindings=verify_mix(job,spec['sound_plan'],spec['audio'],spec['sound_receipt'])
    sound_spec=json.loads(file('sound_plan').read_text())
    if abs(sound_spec['duration_s']-spec['duration_s'])>1e-6:raise ValueError('Sound/film duration mismatch')
    scene=planfile
    if audio.suffix.lower()!='.wav':raise ValueError('Use measured WAV narration/mix')
    raw=subprocess.run([os.environ.get("VIC_FFPROBE", "ffprobe"),'-v','error','-show_entries','format=duration','-of','json',str(audio)],capture_output=True,text=True,check=True)
    ad=float(json.loads(raw.stdout)['format']['duration']);duration=spec['duration_s'];fps=30
    if type(duration) not in (int,float) or not math.isfinite(duration) or duration<=0 or abs(duration*fps-round(duration*fps))>1e-6 or ad>duration+.01:raise ValueError('duration must be finite/frame-aligned and cover the complete supplied audio')
    chunks=json.loads(chunkfile.read_text());chunks=chunks.get('chunks') if isinstance(chunks,dict) else chunks
    caps=[];last=0
    for c in chunks:
        start=float(c['start_s']);end=float(c['end_s']);text=c['visible_text']
        if not isinstance(text,str) or not text.strip() or not (last-1e-6<=start<end<=ad+.01):raise ValueError('Invalid approved caption chunk or timing')
        groups=[];part=''
        for token in re.findall(r'\S+\s*|\s+',text):
            if part and len(part+token)>64:groups.append(part);part=''
            part+=token
        if part:groups.append(part)
        if ''.join(groups)!=text:raise ValueError('Caption text reconstruction changed')
        weight=sum(len(x) for x in groups);t=start
        for i,g in enumerate(groups):
            e=end if i==len(groups)-1 else t+(end-start)*len(g)/weight;caps.append(dict(start=t,end=e,text=g));t=e
        last=end
    shots=spec['shots'];cursor=0
    if not shots:raise ValueError('No shots')
    for i,sh in enumerate(shots):
        start=sh['start'];end=sh['end']
        if not all(type(x) in (int,float) and math.isfinite(x) for x in [start,end]) or abs(start-cursor)>1e-5 or end<=start:raise ValueError('Shots must cover the whole film without gaps/overlap')
        if not isinstance(sh.get('bg'),str) or sh.get('pose','pose_present') not in ['pose_stand','pose_present','pose_point','pose_explain','pose_greeting_bow']:raise ValueError('Explicit background and calibrated presenter pose required')
        sh['index']=i;sh.setdefault('pose','pose_present');cursor=end
    if abs(cursor-duration)>1e-5:raise ValueError('Last shot must include audio pauses and tail exactly')
    envelope=json.loads(envfile.read_text())
    if not isinstance(envelope,list) or len(envelope)<math.floor(last*100)-1 or not all(type(x) in (int,float) and math.isfinite(x) and 0<=x<=1 for x in envelope):raise ValueError('Envelope must cover narration in normalized10ms samples')
    envelope=envelope+[0]*max(0,math.ceil(duration*100)-len(envelope))
    presenter=json.loads((ROOT/'templates/presenter-assets.json').read_text());assets={};asset_inputs={};presenter_copies=[]
    for sh in shots:validate_presenter(sh,presenter)
    for key,rec in presenter.items():
        src=Path(rec['path'])
        if not src.is_file() or digest(src)!=rec['sha256']:raise ValueError('Calibrated presenter source changed: '+key)
        dst=job/'_vic_presenter'/(key+src.suffix)
        assets[key]=dst.as_uri();asset_inputs[key]=dict(path=str(dst.relative_to(job)),sha256=rec['sha256']);presenter_copies.append((src,dst))
    for key,path in spec.get('assets',{}).items():
        p=(job/path).resolve()
        if key in assets or not p.is_relative_to(job) or not p.is_file() or p.suffix.lower() not in ['.png','.jpg','.jpeg','.webp','.svg']:raise ValueError('New assets must be job-local images with fresh aliases')
        assets[key]=p.as_uri();asset_inputs[key]=dict(path=str(p.relative_to(job)),sha256=digest(p))
    rigs=spec.get('rigs',{})
    for key,rig in rigs.items():
        if key not in asset_inputs or key.startswith('pose_'):raise ValueError('Narrative rig asset missing or presenter override attempted')
        for part,n in [('head',4),('hand',6),('finger',4),('page',4),('file',4),('robot',4)]:
            if part not in rig and part!='head':continue
            a=rig.get(part)
            if not isinstance(a,list) or len(a)!=n or not all(type(v) in (int,float) and math.isfinite(v) for v in a) or a[-1]<=0 or a[-2]<=0:raise ValueError('Invalid rig landmark '+part)
        if not isinstance(rig.get('eyes'),list):raise ValueError('Rig eyes missing')
        for a in rig['eyes']+rig.get('robotEyes',[]):
            if len(a)!=4 or not all(type(v) in (int,float) and math.isfinite(v) for v in a) or min(a[-2:])<=0:raise ValueError('Invalid eye landmarks')
        scale=rig.get('motionScale',1)
        if type(scale) not in (int,float) or not 0<=scale<=1:raise ValueError('Keep motionScale in the tested0..1 range; other amplitudes need a separately checked rig')
        for kind,events in rig.get('cues',{}).items():
            if kind not in ['blink','robotBlink','nod','hand','finger','page','file','robot']:raise ValueError('Unknown action cue')
            for e in events:
                st=e['start'];d=e['duration']
                if not all(type(v) in (int,float) and math.isfinite(v) for v in [st,d]) or not 0<=st<duration or d<=0 or st+d>duration+.001:raise ValueError('Invalid motion cue time')
    code='const visualPlan='+json.dumps(plan,ensure_ascii=False).replace('<',r'\u003c')+';\n'+(ROOT/'scripts/visual_ops.js').read_text()
    puppet=(ROOT/'scripts/cartoon_motion.js').read_text().replace('__RIGS__',json.dumps(rigs,ensure_ascii=False))
    html=(ROOT/'templates/renderer.html').read_text();values={'__ENVELOPE__':json.dumps(envelope),'__CAPTIONS__':json.dumps(caps,ensure_ascii=False),'__SHOTS__':json.dumps(shots,ensure_ascii=False),'__ASSETS__':json.dumps(assets),'__PALETTE__':json.dumps(spec.get('palette',{})),'__PUPPET__':puppet,'__SCENES__':code}
    for token in ['__ENVELOPE__','__CAPTIONS__','__SHOTS__','__ASSETS__','__PALETTE__']:
        values[token]=values[token].replace('<',r'\u003c')
    for token,value in values.items():
        if html.count(token)!=1:raise ValueError('Template contract changed at '+token)
        html=html.replace(token,value)
    (job/'_vic_presenter').mkdir()
    for src,dst in presenter_copies:shutil.copy2(src,dst)
    target.write_text(html)
    receipt=dict(duration_s=duration,fps=fps,frames=round(duration*fps),source_sha256=digest(target),audio=str(audio.relative_to(job)),audio_sha256=digest(audio),chunks_sha256=digest(chunkfile),scenes_sha256=digest(scene),visual_contract=contract,inputs={k:dict(path=str(p.relative_to(job)),sha256=digest(p)) for k,p in [('audio',audio),('envelope',envfile),('chunks',chunkfile),('visual_plan',scene),('job',job/'job.json')]},assets=asset_inputs,scope='Bound job-local inputs; not content approval or media QA',caption_timing='Estimated phrases within measured chunks')
    receipt['sound_design']={'plan':spec['sound_plan'],'receipt':spec['sound_receipt'],'target_lufs':sound_spec.get('target_lufs',-18),'true_peak_dbtp':sound_spec.get('true_peak_dbtp',-1.5)}
    receipt['inputs'].update({'sound:'+name:dict(path=name,sha256=h) for name,h in sound_bindings.items()})
    (job/'build.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2));(job/'captions.json').write_text(json.dumps(caps,ensure_ascii=False,indent=2));(job/'shots.json').write_text(json.dumps(shots,ensure_ascii=False,indent=2))
    print(json.dumps(receipt,ensure_ascii=False))
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--job',required=True);prepare(ap.parse_args().job)

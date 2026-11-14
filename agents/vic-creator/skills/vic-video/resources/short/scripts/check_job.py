import os
#!/usr/bin/env python3
"""Mechanical source/rig/optional encode QA. No creative or owner acceptance claim."""
from pathlib import Path
import argparse,json,subprocess,math,hashlib,re
from playwright.sync_api import sync_playwright
from prepare_job import verify_inputs

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def check(job,movie,report):
    job=Path(job).resolve();m=json.loads((job/'build.json').read_text());source=job/'video.html';dest=(job/report).resolve()
    if not dest.is_relative_to(job) or dest.exists():raise ValueError('Use a fresh job-local report')
    if sha(source)!=m['source_sha256']:raise ValueError('Stale prepared source hash')
    verify_inputs(job,m)
    d=m['duration_s'];errors=[];bad=[];trace_checks=0;trace_defects=[]
    plan=json.loads((job/m['inputs']['visual_plan']['path']).read_text()) if 'visual_plan' in m['inputs'] else None
    states={}
    timed=json.loads((job/'shots.json').read_text()) if plan else []
    with sync_playwright() as p:
        b=p.chromium.launch(executable_path=os.environ.get("VIC_CHROME"),args=['--allow-file-access-from-files','--disable-gpu']);pg=b.new_page(viewport={'width':1080,'height':1920});pg.on('pageerror',lambda e:errors.append(str(e)));pg.goto(source.as_uri());pg.wait_for_function('isReady()',timeout=30000);pg.evaluate('document.fonts.ready')
        pg.evaluate('''()=>{const old=label;label=function(c,...args){const n=LAYOUT.length,m=c.getTransform();old(c,...args);for(let i=n;i<LAYOUT.length;i++){let a=LAYOUT[i],p=[[a.x0,a.y0],[a.x0,a.y1],[a.x1,a.y0],[a.x1,a.y1]].map(([x,y])=>({x:m.a*x+m.c*y+m.e,y:m.b*x+m.d*y+m.f}));a.x0=Math.min(...p.map(p=>p.x));a.x1=Math.max(...p.map(p=>p.x));a.y0=Math.min(...p.map(p=>p.y));a.y1=Math.max(...p.map(p=>p.y));}};}''')
        for n in range(round(d*30)):
            t=n/30;pg.evaluate('seekFrame',t);a=pg.evaluate('''()=>({labels:LAYOUT,caption:subChip.textContent,rect:subChip.getBoundingClientRect().toJSON(),presenter:window.PRESENTER_BOUNDS||null,trace:window.VISUAL_TRACE||null})''')
            if plan:
                expected=next((x for x in timed if x['start']<=t<x['end']),None)
                row=next((x for x in plan['shots'] if expected and x['id']==expected['id']),None);trace=a['trace']
                if not row or not trace or trace['shot']!=row['id']:
                    if len(trace_defects)<12:trace_defects.append({'time_s':t,'error':'missing/wrong structured scene'})
                else:
                    by={o['id']:o for o in trace['objects']};trace_checks+=1
                    for o in row['objects']:
                        actual=by.get(o['id'])
                        if not actual or actual['kind']!=o['kind'] or (o['kind']=='sprite' and actual['asset']!=o['asset']):
                            if len(trace_defects)<12:trace_defects.append({'time_s':t,'object':o['id'],'error':'missing bound visual'})
                        elif actual['x']<20 or actual['y']<140 or actual['x']+actual['w']>1060 or actual['y']+actual['h']>1335:
                            if len(trace_defects)<12:trace_defects.append({'time_s':t,'object':o['id'],'error':'object bounds'})
                    for ix,ac in enumerate(row['actions']):
                        key=(row['id'],ix);obj=by.get(ac['object']);local=t-expected['start']
                        if obj and ac['at']-.04<=local<=ac['at']+ac['duration']+.04:
                            values=[obj[k] for k in ['x','y','ink','open','alpha']]
                            state=states.setdefault(key,{'min':values[:],'max':values[:],'samples':0,'op':ac['op']})
                            state['samples']+=1;state['min']=[min(x,y) for x,y in zip(state['min'],values)];state['max']=[max(x,y) for x,y in zip(state['max'],values)]
            failures=[x for x in a['labels'] if x['x0']<20 or x['x1']>1060 or x['y0']<20 or x['y1']>1335]
            rc=a['rect'];pr=a.get('presenter')
            presenter_bad=bool(pr and (pr['x']<0 or pr['y']<0 or pr['x']+pr['width']>1080 or pr['y']+pr['height']>1920))
            presenter_overlap=bool(pr and a['caption'] and pr['x']<rc['right'] and pr['x']+pr['width']>rc['left'] and pr['y']<rc['bottom'] and pr['y']+pr['height']>rc['top'])
            if failures or presenter_bad or presenter_overlap or (a['caption'] and (rc['bottom']>1580 or rc['left']<40 or rc['right']>1040)):
                if len(bad)<12:bad.append(dict(time_s=t,labels=failures,caption_rect=rc,presenter_rect=pr,presenter_overlap=presenter_overlap))
        rig=pg.evaluate('''()=>{let folds=0,tests=0,minRatio=1;const ar=p=>{let[a,b,c]=p;return(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);};for(const key of Object.keys(puppetRigs)){const r=puppetRigs[key],m=makePuppet(loadedImages[key],r),times=new Set([0]);for(const es of Object.values(r.cues||{}))for(const e of es)for(let i=0;i<=Math.ceil(e.duration*30);i++)times.add(e.start+Math.min(e.duration,i/30));for(const t of times){const points=m.points.map(([x,y])=>puppetPoint(x,y,r,t));for(const tri of m.tris){const ratio=ar(tri.map(i=>points[i]))/ar(tri.map(i=>m.points[i]));minRatio=Math.min(minRatio,ratio);if(ratio<=0)folds++;tests++;}}m.gl.getExtension('WEBGL_lose_context')?.loseContext();}return{folds,tests,minRatio};}''');b.close()
    if plan:
        for row in plan['shots']:
            for ix,ac in enumerate(row['actions']):
                st=states.get((row['id'],ix));prop={'move':0,'transfer':0,'write':2,'erase':2,'open':3}.get(ac['op'])
                delta=max(st['max'][j]-st['min'][j] for j in ([0,1] if prop==0 else [prop])) if st and prop is not None else 0
                if not st or st['samples']<2 or (prop is not None and delta < (20 if prop==0 else .2)) or (ac['op']=='pose' and not rig['tests']):
                    trace_defects.append({'shot':row['id'],'action':ix,'error':'operation not observed or no usable rig samples'})
    data=dict(source_sha256=m['source_sha256'],source_frames=round(d*30),javascript_errors=errors,bounds_defects=bad,rig_geometry=rig,limits=['Mechanical QA only','No semantic motion/factual/continuous listening certification','Estimated phrase captions and energy-driven narrator mouth'])
    data.update(visual_plan_trace={'frames':trace_checks,'defects':trace_defects,'scope':'Bound renderer state only, not semantic or encoded creative acceptance'},creative_status='NOT_VERIFIED')
    if movie:
        path=(job/movie).resolve()
        if not path.is_relative_to(job) or not path.is_file():raise ValueError('Movie missing/outside job')
        receipt=json.loads(path.with_suffix('.receipt.json').read_text())
        if sha(path)!=receipt['sha256'] or receipt['source_sha256']!=m['source_sha256']:raise ValueError('Encode receipt/hash mismatch')
        info=json.loads(subprocess.run([os.environ.get("VIC_FFPROBE", "ffprobe"),'-v','error','-count_frames','-show_streams','-show_format','-of','json',str(path)],capture_output=True,text=True,check=True).stdout)
        vs=next(x for x in info['streams'] if x['codec_type']=='video');aus=next(x for x in info['streams'] if x['codec_type']=='audio')
        if int(vs['nb_read_frames'])!=receipt['frames'] or vs['width']!=1080 or vs['height']!=1920 or vs['avg_frame_rate']!='30/1' or vs['codec_name']!='h264' or aus['codec_name']!='aac':raise ValueError('Encode contract mismatch')
        dec=subprocess.run([os.environ.get("VIC_FFMPEG", "ffmpeg"),'-nostdin','-v','error','-i',str(path),'-f','null','-'],capture_output=True,text=True,check=True)
        if dec.stderr.strip():raise ValueError('Decode errors: '+dec.stderr[:300])
        loud=subprocess.run([os.environ.get("VIC_FFMPEG", "ffmpeg"),'-nostdin','-hide_banner','-i',str(path),'-af','loudnorm=I=-18:TP=-1.5:LRA=9:print_format=json','-f','null','-'],capture_output=True,text=True,check=True)
        level=json.loads(re.findall(r'\{[^{}]*"input_i"[^{}]*\}',loud.stderr,re.S)[-1]);data.update(movie_sha256=receipt['sha256'],duration_s=info['format']['duration'],decode='PASS',frames=int(vs['nb_read_frames']),loudness=level)
    if movie and m.get('sound_design'):
        policy=m['sound_design'];levels=data['loudness'];audio_defects=[]
        actual_i=float(levels['input_i']);actual_tp=float(levels['input_tp'])
        if not math.isfinite(actual_i) or abs(actual_i-policy['target_lufs'])>1.5:audio_defects.append('Encoded loudness outside planned target tolerance')
        if not math.isfinite(actual_tp) or actual_tp>policy['true_peak_dbtp']+.5:audio_defects.append('Encoded true peak exceeds planned headroom')
        data['sound_design_qa']={'defects':audio_defects,'listening':'NOT_VERIFIED','policy':policy}
        errors.extend(audio_defects)
    data['mechanical_pass']=not(errors or bad or rig['folds'] or trace_defects);dest.write_text(json.dumps(data,ensure_ascii=False,indent=2));print(json.dumps(data,ensure_ascii=False))
    if not data['mechanical_pass']:raise SystemExit(2)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--job',required=True);p.add_argument('--movie');p.add_argument('--report',default='qa.json');a=p.parse_args();check(a.job,a.movie,a.report)

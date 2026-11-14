"""Local structured visual plan: validate bindings, not semantic truth or artistic quality."""
import json, math, re
from pathlib import Path
KINDS={'sprite','sheet','folder','device','notebook','token'}
OPS={'move','transfer','write','erase','open','pose'}
def number(x):return type(x) in (int,float) and math.isfinite(x)
def validate_plan(job,spec):
    rel=spec.get('visual_plan')
    if not isinstance(rel,str):raise ValueError('visual_plan required: use references/visual-plan.md; text-card source is not a replacement')
    path=(job/rel).resolve()
    if not path.is_relative_to(job) or not path.is_file():raise ValueError('visual_plan must be job-local JSON')
    plan=json.loads(path.read_text())
    if plan.get('style') not in ['visual-story','ui-motion']:raise ValueError('Choose visual-story or ui-motion')
    rows=plan.get('shots',[]);shots=spec['shots'];assets=spec.get('assets',{});rigs=spec.get('rigs',{})
    if len(rows)!=len(shots) or not rows:raise ValueError('Plan must bind every timed shot exactly once')
    used=set();summary=[];seen=set()
    for i,(row,sh) in enumerate(zip(rows,shots)):
        sid=sh.get('id')
        if not isinstance(sid,str) or not re.fullmatch(r'[A-Za-z0-9_-]+',sid) or sid in seen or row.get('id')!=sid:raise ValueError('Unique matching shot IDs required')
        seen.add(sid);objects=row.get('objects',[])
        if not objects:raise ValueError(sid+': concrete objects required, not headings/cards')
        by={}
        for o in objects:
            oid=o.get('id')
            if not isinstance(oid,str) or not re.fullmatch(r'[A-Za-z0-9_-]+',oid) or oid in by:raise ValueError(sid+': unique object ID required')
            if o.get('kind') not in KINDS:raise ValueError(sid+': unsupported object kind')
            if not isinstance(o.get('meaning'),str) or not o['meaning'].strip():raise ValueError(sid+': state what each object represents')
            if not all(number(o.get(k)) for k in ['x','y','w','h']) or min(o['w'],o['h'])<=0:raise ValueError(sid+': finite positive object geometry required')
            if o['x']<40 or o['y']<160 or o['x']+o['w']>1040 or o['y']+o['h']>1320:raise ValueError(sid+': object outside visual safe region')
            if o['kind']=='sprite':
                if o.get('asset') not in assets or o.get('asset','').startswith('pose_'):raise ValueError(sid+': narrative illustration asset missing; VIC presenter does not satisfy it')
                used.add(o['asset'])
            by[oid]=o
        if row.get('primary') not in by:raise ValueError(sid+': choose a concrete primary object')
        hero=by[row['primary']]
        if hero['w']*hero['h']<140000:raise ValueError(sid+': primary is too small for the vertical scene; enlarge it')
        labels=row.get('labels',[])
        if len(labels)>3:raise ValueError(sid+': use at most3 short semantic labels; speech belongs in captions')
        for label in labels:
            txt=label.get('text','')
            if not isinstance(txt,str) or not txt.strip() or len(txt)>100 or '\n' in txt:raise ValueError(sid+': labels must be short single phrases, not narration paragraphs')
            if not all(number(label.get(k)) for k in ['x','y','size']) or not 24<=label['size']<=64 or not 40<=label['x']<=1040 or not 180<=label['y']<=1320:raise ValueError(sid+': invalid label layout')
        actions=row.get('actions',[])
        if not actions:raise ValueError(sid+': meaningful operation required; entrance/fade alone does not qualify')
        end=sh['end']-sh['start'];intervals=[]
        for a in actions:
            op=a.get('op');actor=a.get('object');st=a.get('at');dur=a.get('duration')
            if op not in OPS or actor not in by:raise ValueError(sid+': action/object missing or unsupported')
            if not number(st) or not number(dur) or st<0 or dur<.25 or st+dur>end+.001:raise ValueError(sid+': invalid local action timing')
            o=by[actor]
            if op in ['move','transfer']:
                to=a.get('to')
                if not isinstance(to,list) or len(to)!=2 or not all(number(v) for v in to):raise ValueError(sid+': destination [x,y] required')
                if to[0]<40 or to[1]<160 or to[0]+o['w']>1040 or to[1]+o['h']>1320:raise ValueError(sid+': destination outside safe region')
                if math.hypot(to[0]-o['x'],to[1]-o['y'])<40:raise ValueError(sid+': negligible movement is not an operation')
                if op=='transfer' and (a.get('target') not in by or a['target']==actor):raise ValueError(sid+': transfer needs a distinct visible receiver')
                if op=='transfer':
                    target=by[a['target']]
                    if to[0]+o['w']<=target['x'] or to[0]>=target['x']+target['w'] or to[1]+o['h']<=target['y'] or to[1]>=target['y']+target['h']:raise ValueError(sid+': transfer must reach its receiver')
            if op in ['write','erase'] and o['kind'] not in ['sheet','notebook','device']:raise ValueError(sid+': write/erase needs a writable object')
            if op=='open' and o['kind'] not in ['folder','notebook']:raise ValueError(sid+': open needs a folder/notebook')
            if op=='pose':
                key=o.get('asset');kind=a.get('cue')
                if o['kind']!='sprite' or key not in rigs or kind not in rigs[key].get('cues',{}):raise ValueError(sid+': pose must bind an actual calibrated rig cue')
                cues=rigs[key]['cues'][kind]
                if not any(abs(c['start']-(sh['start']+st))<.04 and abs(c['duration']-dur)<.04 for c in cues):raise ValueError(sid+': rig cue must use matching film-global time')
            if not isinstance(a.get('result'),str) or not a['result'].strip():raise ValueError(sid+': name the visible action result')
            # Avoid accidental conflicting timelines on the same property.
            prop='position' if op in ['move','transfer'] else 'ink' if op in ['write','erase'] else op
            if any(actor==x and prop==y and st<e and st+dur>b for x,y,b,e in intervals):raise ValueError(sid+': overlapping actions on the same property')
            intervals.append((actor,prop,st,st+dur))
        summary.append({'id':sid,'objects':len(objects),'actions':len(actions),'labels':len(labels)})
    if plan['style']=='visual-story' and not used:raise ValueError('Visual Story requires relevant narrative illustration(s), not presenter-only UI cards. Missing art is a blocker.')
    return path,plan,{'style':plan['style'],'shots':summary,'illustration_assets':sorted(used),'scope':'Structure and bindings only; encoded creative review still required'}

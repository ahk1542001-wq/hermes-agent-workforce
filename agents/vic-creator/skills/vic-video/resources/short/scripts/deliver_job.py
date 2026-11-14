#!/usr/bin/env python3
"""Verify exact encoded technical QA plus attributable creative review before completion receipt."""
from pathlib import Path
import argparse,json,hashlib,math
from prepare_job import verify_inputs
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def deliver(job,movie,qa,review,output):
    job=Path(job).resolve()
    def local(n):
        p=(job/n).resolve()
        if not p.is_relative_to(job) or not p.is_file():raise ValueError('Missing/outside local evidence: '+str(n))
        return p
    movie=local(movie);qfile=local(qa);rfile=local(review);dest=(job/output).resolve()
    if not dest.is_relative_to(job) or dest.exists() or dest.is_symlink():raise ValueError('Use fresh job-local completion receipt')
    build=json.loads(local('build.json').read_text());verify_inputs(job,build)
    if sha(local('video.html'))!=build['source_sha256']:raise ValueError('Prepared source changed')
    q=json.loads(qfile.read_text());r=json.loads(rfile.read_text());h=sha(movie);receipt=json.loads(local(str(movie.relative_to(job).with_suffix('.receipt.json'))).read_text())
    if not build.get('visual_contract') or receipt.get('start_s')!=0 or receipt.get('frames')!=build['frames'] or abs(receipt.get('duration_s',0)-build['duration_s'])>1e-5:raise ValueError('Completion needs the entire bound timeline, not a partial proof/legacy source')
    if not q.get('mechanical_pass') or q.get('decode')!='PASS' or q.get('movie_sha256')!=h or q.get('source_sha256')!=build['source_sha256'] or receipt['sha256']!=h:raise ValueError('Exact encoded QA/receipt required; source-only PASS is insufficient')
    role=r.get('role')
    valid_reviewer=role=='independent-reviewer' or (role=='main-orchestrator-reviewer' and r.get('review_phase')=='post_render')
    if r.get('movie_sha256')!=h or r.get('verdict')!='PASS' or not valid_reviewer or not str(r.get('reviewer_session','')).strip():raise ValueError('Attributable encoded post-render creative review required; an execution PASS alone cannot close delivery')
    plan=json.loads(local(build['inputs']['visual_plan']['path']).read_text());timed=json.loads(local('shots.json').read_text());samplemap={s['id']:s for s in r.get('shots',[])}
    for row,sh in zip(plan['shots'],timed):
        evidence=samplemap.get(row['id'])
        if not evidence or evidence.get('verdict')!='PASS' or evidence.get('observed_objects')!=[o['id'] for o in row['objects']] or evidence.get('observed_actions')!=[a['op'] for a in row['actions']]:raise ValueError('Every planned object/action needs explicit encoded review: '+row['id'])
        if not str(evidence.get('observation','')).strip():raise ValueError('Timecoded review observation required')
        times=evidence.get('times_s',[])
        if len(times)<2 or not all(type(t) in (int,float) and math.isfinite(t) and sh['start']<=t<sh['end'] for t in times):raise ValueError('Review before/result samples required inside every shot')
        for frame in evidence.get('frames',[]):local(frame)
        if len(evidence.get('frames',[]))<2:raise ValueError('Encoded frame evidence paths required')
    if r.get('defects') or not isinstance(r.get('limits'),list) or not r['limits']:raise ValueError('Report defects and honest viewing/listening limits')
    out={'status':'REVIEWED_CANDIDATE_PENDING_OWNER_ACCEPTANCE','movie_sha256':h,'qa_sha256':sha(qfile),'review_sha256':sha(rfile),'reviewer_session':r['reviewer_session'],'reviewer_role':role,'review_phase':r.get('review_phase'),'scope':'Evidence bindings verified; reviewer accuracy not automatically proven; only owner accepts final'}
    dest.write_text(json.dumps(out,indent=2));print(json.dumps(out))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--job',required=True);p.add_argument('--movie',required=True);p.add_argument('--qa',required=True);p.add_argument('--review',required=True);p.add_argument('--output',default='delivery.json');a=p.parse_args();deliver(a.job,a.movie,a.qa,a.review,a.output)

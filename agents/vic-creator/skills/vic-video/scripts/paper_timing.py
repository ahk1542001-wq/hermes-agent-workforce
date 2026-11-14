"""Map a verified shared-Voice assembly to paper-engine timing without changing audio."""
import argparse, hashlib, json, re, wave
from pathlib import Path

def convert(receipt_path, voice_path, groups_path, output_path):
    receipt_path,voice_path,groups_path,output_path=map(Path,(receipt_path,voice_path,groups_path,output_path))
    if output_path.exists():raise ValueError('Output already exists; use a fresh job path')
    receipt=json.loads(receipt_path.read_text());groups=json.loads(groups_path.read_text())
    if hashlib.sha256(voice_path.read_bytes()).hexdigest()!=receipt.get('sha256'):raise ValueError('Voice hash differs from assembly receipt')
    with wave.open(str(voice_path)) as w:
        sr,total=w.getframerate(),w.getnframes()
        if (sr,w.getnchannels(),w.getsampwidth())!=(48000,1,2):raise ValueError('Expected shared Voice 48kHz mono PCM16')
    chunks=[];seen=set();previous_end=0
    for i,c in enumerate(receipt.get('chunks',[]),1):
        ident=c['id'];a,b=c['start_sample'],c['end_sample']
        if not isinstance(ident,str) or not re.fullmatch(r'[A-Za-z0-9_-]+',ident) or ident in seen:raise ValueError('Invalid or duplicate chunk ID')
        if type(a) is not int or type(b) is not int or not 0<=previous_end<=a<b<=total:raise ValueError('Invalid or overlapping sample interval')
        for name,val in [('start_s',a),('end_s',b)]:
            if name in c and abs(c[name]-val/sr)>1/sr:raise ValueError('Seconds/sample timing mismatch')
        text=c.get('visible_text')
        if not isinstance(text,str) or not text.strip():raise ValueError('Missing approved visible text')
        chunks.append(dict(num=i,id=ident,text=text,spoken_text=c.get('spoken_text',text),start_sample=a,end_sample=b,start_s=a/sr,end_s=b/sr))
        previous_end=b;seen.add(ident)
    if not chunks or not groups:raise ValueError('Chunks and chapter groups are required')
    cursor=1;ids=set()
    for g in groups:
        ident=g['id'];a,b=g['first'],g['last']
        if not isinstance(ident,str) or not re.fullmatch(r'[A-Za-z0-9_-]+',ident) or ident in ids:raise ValueError('Invalid or duplicate scene ID')
        if type(a) is not int or type(b) is not int or a!=cursor or not a<=b<=len(chunks):raise ValueError('Groups must cover chunks exactly once in order')
        ids.add(ident);cursor=b+1
    if cursor!=len(chunks)+1:raise ValueError('Groups do not cover the final chunk')
    scenes=[]
    for i,g in enumerate(groups):
        start=0 if i==0 else chunks[g['first']-1]['start_sample']
        end=chunks[groups[i+1]['first']-1]['start_sample'] if i+1<len(groups) else total
        scenes.append(dict(id=g['id'],first=g['first'],last=g['last'],start_sample=start,end_sample=end,start_s=start/sr,end_s=end/sr,duration_s=(end-start)/sr))
    result=dict(sample_rate=sr,total_samples=total,total_duration_s=total/sr,source_sha256=receipt['sha256'],chunks=chunks,scenes=scenes,scope='Timing adapter only; audio and approved text unchanged; pauses/tail preserved')
    output_path.parent.mkdir(parents=True,exist_ok=True)
    with output_path.open('x') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['receipt','voice','groups','out']:p.add_argument('--'+name,required=True)
    a=p.parse_args()
    try:r=convert(a.receipt,a.voice,a.groups,a.out)
    except (ValueError,KeyError,TypeError,wave.Error) as e:p.error(str(e))
    print(json.dumps(dict(chunks=len(r['chunks']),scenes=len(r['scenes']),seconds=r['total_duration_s'],audio_changed=False)))
if __name__=='__main__':main()

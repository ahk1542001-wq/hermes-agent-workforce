"""Bind verified shared-voice outputs to a film's timing/captions/audio module.
This does not synthesize, allocate runtimes, upload data or grant permissions.
"""
import argparse,array,base64,hashlib,json,math,re,subprocess,wave
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--work',required=True);p.add_argument('--output',required=True);p.add_argument('--module',required=True);p.add_argument('--sound-import',required=True);p.add_argument('--design-times',required=True);p.add_argument('--separate-stems',action='store_true');a=p.parse_args()
work=Path(a.work).resolve();out=Path(a.output).resolve();out.mkdir(parents=True,exist_ok=True);module=Path(a.module).resolve();design=json.loads(Path(a.design_times).read_text())
assert re.fullmatch(r'\./[A-Za-z0-9_-]+',a.sound_import),'Use a project-local sound module exporting makeSound'
r=json.loads((work/'assembled/receipt.json').read_text());state=json.loads((work/'status.json').read_text());assert state.get('runtime_stopped') is True
raw=work/'assembled/narration.wav';sha=lambda q:hashlib.sha256(Path(q).read_bytes()).hexdigest();assert sha(raw)==r['sha256']
chunks=r['chunks'];assert len(design)==len(chunks)+1 and design[0]==0 and all(b>aa for aa,b in zip(design,design[1:]))
proc=subprocess.run(['ffmpeg','-hide_banner','-i',str(raw),'-af','loudnorm=I=-17:TP=-2:LRA=11:print_format=json','-f','null','-'],capture_output=True,text=True,check=True)
measure=json.JSONDecoder().raw_decode(proc.stderr[proc.stderr.rindex('{'):])[0];lufs,peak=map(float,[measure['input_i'],measure['input_tp']]);assert math.isfinite(lufs) and lufs>-45
# Correct only measured level, respecting peaks. No word trim, pitch or time stretch.
gain=0 if -18.5<=lufs<=-15.5 else min(-17-lufs,-2-peak)
master=out/'narration-levelled.wav';subprocess.run(['ffmpeg','-v','error','-i',str(raw),'-af',f'volume={gain}dB','-ar','48000','-ac','1','-c:a','pcm_s16le','-y',str(master)],check=True)
with wave.open(str(master)) as w:
    assert w.getframerate()==48000 and w.getnchannels()==1
    pcm=w.readframes(w.getnframes())
values=array.array('h',pcm);duration=len(values)/48000;frames=math.ceil((duration+.25)*30);total=frames/30
levels=[]
for f in range(frames):
    part=values[f*1600:(f+1)*1600];levels.append(math.sqrt(sum((v/32768)**2 for v in part)/max(1,len(part))))
q=sorted(levels)[int(len(levels)*.7)];levels=[round(min(1,v/max(.005,q)),3) for v in levels]
times=[c['start_s'] for c in chunks]+[total];caps=[{'from':round(c['start_s']*30),'to':round(c['end_s']*30),'text':c['visible_text']} for c in chunks]
quiet=[];tail_measurements=[]
for i,c in enumerate(chunks[:-1]):
    end=min(len(values),round(c['end_s']*48000));start=end
    # Only contiguous measured near-zero trailing blocks, at most 250 ms.
    # This annotates existing quiet; it never trims or changes the waveform.
    for stop in range(end,max(0,end-12000),-480):
        begin=max(0,stop-480);part=values[begin:stop]
        rms=math.sqrt(sum((v/32768)**2 for v in part)/max(1,len(part)))
        if rms>=.001:break
        start=begin
    tail_measurements.append(dict(chunk=i+1,chunk_end_s=end/48000,measured_quiet_start_s=start/48000,rms_threshold=.001,block_ms=10,max_lookback_ms=250))
    quiet.append([max(0,math.floor(start/48000*30)),math.ceil(chunks[i+1]['start_s']*30),'Measured near-zero sentence tail plus explicit assembly pause; waveform unchanged'])
code="import type {FilmAudio} from './film';\nimport {"+('makeMusic,makeEffects' if a.separate_stems else 'makeSound')+"} from "+json.dumps(a.sound_import)+";\n"
for name,value in [('voiceTimes',times),('voiceLevels',levels),('voiceCaptions',caps),('voiceFrames',frames),('voiceQuiet',quiet)]:code+='export const '+name+'='+json.dumps(value,ensure_ascii=False)+';\n'
code+='const pcm64='+json.dumps(base64.b64encode(pcm).decode())+';\nconst design='+json.dumps(design)+';\n'
code+='''const bytes=Uint8Array.from(atob(pcm64),c=>c.charCodeAt(0)),dv=new DataView(bytes.buffer),voice=new Float32Array(bytes.length/2);for(let i=0;i<voice.length;i++)voice[i]=dv.getInt16(i*2,true)/32768;
function mapTime(t:number){let n=0;while(n<design.length-2&&t>=design[n+1])n++;return voiceTimes[n]+(t-design[n])/(design[n+1]-design[n])*(voiceTimes[n+1]-voiceTimes[n]);}
export const narratedSound:FilmAudio=(sr)=>{const length=Math.ceil(voiceFrames/30*sr),mix=makeSound(sr,voiceFrames/30,mapTime);for(let n=0;n<length;n++){const j=Math.floor(n*48000/sr),v=j<voice.length?voice[j]:0,bg=.28*(1-.6*Math.min(1,Math.abs(v)/.25));mix[0][n]=mix[0][n]*bg+v;mix[1][n]=mix[1][n]*bg+v;}return mix;};
'''
if a.separate_stems:
    old=code[code.index('export const narratedSound:'):]
    code=code[:-len(old)]+"""export const narratedSound:FilmAudio=(sr)=>{const length=Math.ceil(voiceFrames/30*sr),music=makeMusic(sr,voiceFrames/30,mapTime),fx=makeEffects(sr,voiceFrames/30,mapTime),mix:[Float32Array,Float32Array]=[new Float32Array(length),new Float32Array(length)];let envelope=0;for(let n=0;n<length;n++){const j=Math.floor(n*48000/sr),v=j<voice.length?voice[j]:0,target=Math.min(1,Math.abs(v)/.10);envelope+=(target-envelope)*(target>envelope?1/(sr*.015):1/(sr*.25));const duck=.9*(1-.45*envelope);for(let ch=0;ch<2;ch++)mix[ch][n]=v+music[ch][n]*duck+fx[ch][n]*.24;}return mix;};\n"""
module.write_text(code)
(out/'narration-binding.json').write_text(json.dumps(dict(source_sha256=r['sha256'],duration=duration,frames=frames,video_seconds=total,voice_times=times,level_gain_db=gain,input_lufs=lufs,input_true_peak=peak,master_sha256=sha(master),runtime_stopped=True,caption_count=len(caps),separate_music_effects=a.separate_stems,quiet_tail_measurements=tail_measurements,mouth='Narration-only RMS, not phoneme alignment',listening='Not performed by this helper'),indent=2))
def stamp(t):
    ms=round(t*1000);return f'{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d},{ms%1000:03d}'
(out/'captions.srt').write_text('\n\n'.join(f"{i+1}\n{stamp(c['start_s'])} --> {stamp(c['end_s'])}\n{c['visible_text']}" for i,c in enumerate(chunks))+'\n')
print(json.dumps(dict(video_seconds=total,frames=frames,chunks=len(chunks),input_lufs=lufs,level_gain_db=gain)))

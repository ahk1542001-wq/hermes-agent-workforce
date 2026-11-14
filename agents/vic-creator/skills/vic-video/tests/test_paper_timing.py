import hashlib,importlib.util,json,tempfile,unittest,wave
from pathlib import Path
spec=importlib.util.spec_from_file_location('paper_timing',Path(__file__).parents[1]/'scripts/paper_timing.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class TimingContract(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.p=Path(self.tmp.name);self.v=self.p/'synthetic.wav'
  with wave.open(str(self.v),'w') as w:w.setparams((1,2,48000,0,'NONE','NONE'));w.writeframes(b'\0\0'*96000)
  self.r={'sha256':hashlib.sha256(self.v.read_bytes()).hexdigest(),'chunks':[{'id':'a','start_sample':0,'end_sample':24000,'visible_text':'မင်္ဂလာပါ။'},{'id':'b','start_sample':33600,'end_sample':72000,'visible_text':'ဒုတိယ။'}]};self.g=[{'id':'one','first':1,'last':1},{'id':'two','first':2,'last':2}]
 def tearDown(self):self.tmp.cleanup()
 def run_it(self):
  (self.p/'r.json').write_text(json.dumps(self.r));(self.p/'g.json').write_text(json.dumps(self.g));return m.convert(self.p/'r.json',self.v,self.p/'g.json',self.p/'out.json')
 def test_preserves_pause_tail_and_text(self):
  r=self.run_it();self.assertEqual([s['duration_s'] for s in r['scenes']],[.7,1.3]);self.assertEqual(sum(s['end_sample']-s['start_sample'] for s in r['scenes']),96000);self.assertEqual(r['chunks'][0]['text'],'မင်္ဂလာပါ။');self.assertEqual(hashlib.sha256(self.v.read_bytes()).hexdigest(),self.r['sha256'])
 def test_rejects_hash_mismatch(self):
  self.r['sha256']='0'*64
  with self.assertRaises(ValueError):self.run_it()
 def test_rejects_overlapping_speech(self):
  self.r['chunks'][1]['start_sample']=20000
  with self.assertRaises(ValueError):self.run_it()
 def test_rejects_incomplete_groups(self):
  self.g=self.g[:1]
  with self.assertRaises(ValueError):self.run_it()
 def test_refuses_output_overwrite(self):
  self.run_it()
  with self.assertRaises(ValueError):self.run_it()
if __name__=='__main__':unittest.main()

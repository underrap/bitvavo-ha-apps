import hashlib,json,subprocess,sys,tempfile
from pathlib import Path
BASE=Path(__file__).parent
with tempfile.TemporaryDirectory() as d:
 src=Path(d)/'src';out=Path(d)/'out';src.mkdir();cut=200
 rows={
  'raw_events.jsonl':[{'recv_utc_ns':100,'recv_mono_ns':1,'raw':{}},{'recv_utc_ns':300,'recv_mono_ns':2,'raw':{}}],
  'sessions.jsonl':[{'utc_ns':100,'mono_ns':1,'kind':'connect'},{'utc_ns':300,'mono_ns':2,'kind':'disconnect'}],
  'book_checkpoints.jsonl':[{'utc_ns':100,'mono_ns':1,'market':'BTC-EUR','nonce':1,'bids':[['99','1']],'asks':[['101','1']]},{'utc_ns':300,'mono_ns':2,'market':'BTC-EUR','nonce':2,'bids':[['99','1']],'asks':[['101','1']]}]
 }
 for n,xs in rows.items():(src/n).write_text(''.join(json.dumps(x)+'\n' for x in xs))
 cp=subprocess.run([sys.executable,str(BASE/'freeze.py'),'--source',str(src),'--output',str(out),'--cutoff-utc-ns',str(cut),'--m0-version','1.0.5'],capture_output=True,text=True)
 assert cp.returncode==0,cp.stderr+cp.stdout
 mf=json.loads((out/'freeze_manifest.json').read_text());assert mf['research_cutoff_utc_ns']==cut
 assert mf['freeze_id']=='M1A_FREEZE_001'
 assert mf['m0_version']=='1.0.5'
 assert mf['m0_capability']=='persisted_reconstructed_book_checkpoints_v1'
 assert mf['checkpoint_capability_verified'] is True
 for n in rows:
  lines=(out/n).read_text().strip().splitlines();assert len(lines)==1
  assert json.loads(lines[0]).get('recv_utc_ns',json.loads(lines[0]).get('utc_ns'))==100
  assert hashlib.sha256((out/n).read_bytes()).hexdigest()==mf['files'][n]['sha256']
 print('M1A freeze cutoff/hash PASS')

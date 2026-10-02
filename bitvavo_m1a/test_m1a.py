import json,hashlib,tempfile,subprocess,sys
from pathlib import Path
BASE=Path(__file__).parent

def canon(x):return json.dumps(x,sort_keys=True,separators=(',',':'))

def make(root):
 raw=[];ses=[];cps=[];utc0=1800000000000000000;mono0=10000000000;meta={}
 for mi,m in enumerate(('BTC-EUR','BTC-USDC')):
  base=50000+mi*10;nonce=1000+mi*10000
  cps.append({'kind':'book_checkpoint','market':m,'session':1,'utc_ns':utc0,'mono_ns':mono0,'nonce':nonce,
   'bids':[[str(base-1),'2'],[str(base-2),'1'],[str(base-3),'1'],[str(base-4),'1'],[str(base-5),'1']],
   'asks':[[str(base+1),'2'],[str(base+2),'1'],[str(base+3),'1'],[str(base+4),'1'],[str(base+5),'1']]})
  for k in range(1,361):
   t=mono0+k*250000000;nonce+=1;phase=(k%20)-10;bs=1+max(phase,0)/3;az=1+max(-phase,0)/3
   raw.append({'recv_utc_ns':utc0+t-mono0,'recv_mono_ns':t,'session':1,'raw':{'event':'book','market':m,'nonce':nonce,'bids':[[str(base-1),str(bs)]],'asks':[[str(base+1),str(az)]]}})
   if k%4==0:
    side='buy' if phase>=0 else 'sell'
    raw.append({'recv_utc_ns':utc0+t-mono0+1,'recv_mono_ns':t+1,'session':1,'raw':{'event':'trade','market':m,'id':f'{m}-{k}','amount':'0.01','price':str(base),'side':side}})
 raw.sort(key=lambda x:x['recv_mono_ns']);root.mkdir()
 for name,rows in [('raw_events.jsonl',raw),('sessions.jsonl',ses),('book_checkpoints.jsonl',cps)]:
  p=root/name;p.write_text(''.join(canon(x)+'\n' for x in rows));meta[name]={'records':len(rows),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
 (root/'freeze_manifest.json').write_text(json.dumps({'schema':'m1a-freeze-v1','research_cutoff_utc_ns':utc0+100000000000,'research_cutoff_utc':'synthetic','source':'synthetic','files':meta,'freeze_tool_version':'test','m0_version':'1.0.5'}))

with tempfile.TemporaryDirectory() as d:
 r=Path(d)/'f';o=Path(d)/'o';make(r)
 cp=subprocess.run([sys.executable,str(BASE/'analyze.py'),'--input',str(r),'--output',str(o)],text=True,capture_output=True)
 assert cp.returncode==0,cp.stderr+cp.stdout
 x=json.loads((o/'results.json').read_text())
 assert x['protocol']=='M1A-PREREG-v1.3'
 assert x['executor_version']=='1.2.0'
 assert x['decision']=='INCONCLUSIVE'
 assert x['split']['primary_eligible_total']>100
 assert x['primary_confirmatory']['bootstrap']['replicates']==0
 assert (o/'report.md').exists()
 print('M1A v1.3 synthetic E2E PASS')

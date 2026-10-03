import json, hashlib, tempfile, subprocess, sys
from pathlib import Path

BASE=Path(__file__).parent

def canon(x):
    return json.dumps(x,sort_keys=True,separators=(',',':'))

def make(root):
    raw=[]; cps=[]; utc0=1800000000000000000; mono0=10000000000
    for mi,m in enumerate(('BTC-EUR','BTC-USDC')):
        base=50000+mi*10; nonce=1000+mi*10000
        cps.append({
            'kind':'book_checkpoint','market':m,'session':1,'utc_ns':utc0,'mono_ns':mono0,'nonce':nonce,
            'bids':[[str(base-1),'2'],[str(base-2),'1'],[str(base-3),'1'],[str(base-4),'1'],[str(base-5),'1']],
            'asks':[[str(base+1),'2'],[str(base+2),'1'],[str(base+3),'1'],[str(base+4),'1'],[str(base+5),'1']]
        })
        for k in range(1,721):
            t=mono0+k*250000000; nonce+=1; phase=(k%20)-10
            bs=1+max(phase,0)/3; az=1+max(-phase,0)/3
            raw.append({
                'recv_utc_ns':utc0+t-mono0,'recv_mono_ns':t,'session':1,
                'raw':{'event':'book','market':m,'nonce':nonce,
                       'bids':[[str(base-1),str(bs)]],'asks':[[str(base+1),str(az)]]}
            })
            if k%4==0:
                raw.append({
                    'recv_utc_ns':utc0+t-mono0+1,'recv_mono_ns':t+1,'session':1,
                    'raw':{'event':'trade','market':m,'id':f'{m}-{k}','amount':'0.01',
                           'price':str(base),'side':'buy' if phase>=0 else 'sell'}
                })
    raw.sort(key=lambda x:x['recv_mono_ns'])
    root.mkdir()
    meta={}
    for name,rows in [('raw_events.jsonl',raw),('sessions.jsonl',[]),('book_checkpoints.jsonl',cps)]:
        p=root/name
        p.write_text(''.join(canon(x)+'\n' for x in rows))
        meta[name]={'records':len(rows),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    (root/'freeze_manifest.json').write_text(json.dumps({
        'schema':'m1a-freeze-v1',
        'research_cutoff_utc':'synthetic',
        'source':'synthetic',
        'files':meta,
        'freeze_tool_version':'test',
        'm0_version':'1.0.5'
    }))

with tempfile.TemporaryDirectory() as d:
    root=Path(d)/'f'; out=Path(d)/'o'; make(root)
    cp=subprocess.run([sys.executable,str(BASE/'analyze.py'),'--input',str(root),'--output',str(out)],
                      text=True,capture_output=True)
    assert cp.returncode==0,cp.stderr+cp.stdout
    x=json.loads((out/'results.json').read_text())
    assert x['executor_version']=='1.2.0'
    assert x['protocol']=='M1A-PREREG-v1.3'
    assert x['content_protocol']=='M1A-PREREG-v1.2'
    assert x['audit']['BTC-EUR']['monotonic_regressions']==0
    assert x['markets']['BTC-EUR']['primary_eligible_n']>100
    assert x['markets']['BTC-EUR']['confirmatory']['decision']=='INCONCLUSIVE'
    assert (out/'report.md').exists()
    print('M1A v1.3 synthetic E2E PASS')

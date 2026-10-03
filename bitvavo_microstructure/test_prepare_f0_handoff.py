import hashlib,json,subprocess,sys,tempfile
from pathlib import Path
BASE=Path(__file__).parent

def sha(p):
    h=hashlib.sha256();h.update(p.read_bytes());return h.hexdigest()

def make(root,complete=True):
    root.mkdir()
    (root/"paired_books.jsonl").write_text('{"both_ok":true}\n')
    (root/"trade_windows.jsonl").write_text('')
    (root/"failures.jsonl").write_text('')
    state={"completed_duration":complete,"first_pair_ms":1,"stopped_at":"done","pairs_both_ok":10,"pairs_attempted":10}
    (root/"state.json").write_text(json.dumps(state,separators=(',',':')))
    files={}
    for name in ("paired_books.jsonl","trade_windows.jsonl","failures.jsonl","state.json"):
        p=root/name;files[name]={"bytes":p.stat().st_size,"sha256":sha(p)}
    manifest={"version":1,"public_only":True,"book_depth":100,"state":state,"files":files}
    (root/"manifest.json").write_text(json.dumps(manifest,separators=(',',':')))

with tempfile.TemporaryDirectory() as d:
    d=Path(d)
    src=d/"ok";make(src,True)
    out=d/"f0_week1.zip"
    cp=subprocess.run([sys.executable,str(BASE/"prepare_f0_handoff.py"),"--input",str(src),"--output",str(out)],
                      text=True,capture_output=True)
    assert cp.returncode==0,cp.stderr+cp.stdout
    result=json.loads(cp.stdout)
    assert result["status"]=="READY"
    assert out.exists()
    assert out.with_suffix(out.suffix+".sha256").exists()

    src2=d/"incomplete";make(src2,False)
    cp=subprocess.run([sys.executable,str(BASE/"prepare_f0_handoff.py"),"--input",str(src2),"--output",str(d/"bad.zip")],
                      text=True,capture_output=True)
    assert cp.returncode!=0
    assert "completed" in (cp.stderr+cp.stdout).lower()

    # Tamper after manifest creation must be rejected.
    src3=d/"tampered";make(src3,True)
    with (src3/"paired_books.jsonl").open("a") as f:f.write("{}\n")
    cp=subprocess.run([sys.executable,str(BASE/"prepare_f0_handoff.py"),"--input",str(src3),"--output",str(d/"tampered.zip")],
                      text=True,capture_output=True)
    assert cp.returncode!=0
    assert "sha-256 mismatch" in (cp.stderr+cp.stdout).lower()

print("F0 handoff packager PASS")

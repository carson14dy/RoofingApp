"""Disk guard for the running build passes: every 2 minutes, when free space falls under the threshold, remove the
scratch folders of skeptic agents that the workflow journal shows as finished (nobody reads them afterwards), then
the uv package cache; log every action. It never touches a builder's, reviewer's or checker's folder."""
import json, os, shutil, subprocess, sys, time
W = '/root/.claude/projects/-home-user-RoofingApp/7638440a-a008-5ef8-a289-86be0a23e7a7/subagents/workflows'
RUNS = {}
LOG = '/home/user/wt/diskguard.log'
THRESH = 2.5e9
def log(msg):
    with open(LOG, 'a') as f: f.write(time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()) + ' ' + msg + '\n')
def free_bytes(): s = os.statvfs('/home/user'); return s.f_bavail * s.f_frsize
def finished_skeptics(run):
    p = f'{W}/{run}/journal.jsonl'
    if not os.path.exists(p): return []
    pending, finished = [], []
    for line in open(p):
        try: d = json.loads(line)
        except Exception: continue
        if d.get('type') == 'started': pending.append(d.get('label', ''))
        elif d.get('type') == 'result' and pending: finished.append(pending.pop(0))
    return [l.split(':', 1)[1] for l in finished if l.startswith(('skeptic:', 'verify:'))]
def sweep():
    freed = 0
    for run, out in RUNS.items():
        for fid in finished_skeptics(run):
            p = os.path.join(out, 'skeptic-' + fid)
            if os.path.isdir(p):
                sz = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(p) for f in fs)
                shutil.rmtree(p, ignore_errors=True); freed += sz; log(f'removed {p} ({sz/1e6:.0f} MB)')
    return freed
end = time.time() + float(sys.argv[1]) if len(sys.argv) > 1 else time.time() + 7000
log(f'start; free {free_bytes()/1e9:.2f} GB')
while time.time() < end:
    fb = free_bytes()
    if fb < THRESH:
        log(f'free {fb/1e9:.2f} GB under threshold; sweeping')
        sweep()
        if free_bytes() < 2.0e9:
            subprocess.run(['uv', 'cache', 'clean'], capture_output=True); log(f'uv cache cleaned; free {free_bytes()/1e9:.2f} GB')
        log(f'after sweep free {free_bytes()/1e9:.2f} GB')
    time.sleep(120)
log(f'end; free {free_bytes()/1e9:.2f} GB')

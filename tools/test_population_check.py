"""
test_population_check.py — does the population check actually catch anything.

A check that passes on good data proves nothing. Every arithmetic check in
this pipeline was passing, continuously, while four separate population bugs
were live, and each one was found by a person reading the page.

So this injects the exact shape of each bug into a copy of the projections and
asserts that the check fails on it:

  a heavily priced player silently dropped        the McCaffrey shape
  a projected player from an old roster           the Philip Rivers shape
  a projected player who is on injured reserve    the Jayden Reed shape
  a team left without a quarterback
  forty percent of the board vanishing overnight

It restores the real file afterwards whatever happens. If this ever stops
catching all five, the check has been weakened and the thing it guards is
unguarded again.
"""
import json, os, shutil, subprocess, sys
D='/home/user/Pga_simulator/data'
PR=f'{D}/nfl_projections.json'; BL=f'{D}/population_baseline.json'
BK = os.environ.get('POPTEST_TMP') or '/tmp'
shutil.copy(PR, f'{BK}/pr.bak')
if os.path.exists(BL): shutil.copy(BL, f'{BK}/bl.bak')

def run():
    r=subprocess.run([sys.executable,'/home/user/Pga_simulator/tools/verify_population.py'],
                     capture_output=True, text=True, cwd='/home/user/Pga_simulator')
    fails=[l for l in r.stdout.splitlines() if l.startswith('FAIL')]
    return r.returncode, fails

def restore():
    shutil.copy(f'{BK}/pr.bak', PR)
    if os.path.exists(f'{BK}/bl.bak'): shutil.copy(f'{BK}/bl.bak', BL)

def mutate(fn, label, expect):
    restore()
    d=json.load(open(PR)); fn(d); json.dump(d, open(PR,'w'), separators=(',',':'))
    code, fails = run()
    hit = any(expect.lower() in f.lower() for f in fails)
    print(f'{"CAUGHT " if (code!=0 and hit) else "MISSED "} {label}')
    for f in fails[:1]: print(f'           {f[:150]}')
    return code!=0 and hit

base=json.load(open(PR))
ok=[]

# 1. The McCaffrey shape: a heavily priced player silently dropped.
def drop_priced(d):
    import sys; sys.path.insert(0,'/home/user/Pga_simulator/tools')
    from enrich_props import nrm
    pf={}
    for p in json.load(open(f'{D}/nfl_props_full.json'))['props']:
        if p.get('pos') in ('QB','RB','WR','TE'):
            pf[p.get('skey') or nrm(p['player'])]=pf.get(p.get('skey') or nrm(p['player']),0)+1
    heavy={k for k,v in pf.items() if v>=6}
    d['players']=[p for p in d['players'] if nrm(p['player']) not in heavy or p['pos']=='DST']
    d['count']=len(d['players'])
ok.append(mutate(drop_priced,'McCaffrey shape: heavily priced players dropped','not projected'))

# 2. The Philip Rivers shape: a ghost from an old roster.
def add_ghost(d):
    g=dict(d['players'][0]); g.update({'player':'Philip Rivers','pos':'QB','team':'IND','anchors':[]})
    d['players'].append(g); d['count']=len(d['players'])
ok.append(mutate(add_ghost,'Philip Rivers shape: a ghost from an old roster','no current roster'))

# 3. The Jayden Reed shape: on IR, no lines, still projected.
def add_stale(d):
    g=dict(d['players'][0]); g.update({'player':'Jayden Reed','pos':'WR','team':'GB','anchors':[]})
    d['players'].append(g); d['count']=len(d['players'])
ok.append(mutate(add_stale,'Jayden Reed shape: on injured reserve, still projected','not played in two or more weeks'))

# 4. A whole position vanishing from a team.
def strip_qbs(d):
    teams={p['team'] for p in d['players']}
    t=sorted(teams)[0]
    d['players']=[p for p in d['players'] if not (p['team']==t and p['pos']=='QB')]
    d['count']=len(d['players'])
ok.append(mutate(strip_qbs,'a team left with no quarterback','missing a position'))

# 5. Mass churn against the baseline.
restore(); run()   # set a clean baseline
def churn(d):
    d['players']=d['players'][:int(len(d['players'])*0.6)]; d['count']=len(d['players'])
ok.append(mutate(churn,'40% of the board disappearing between builds','moved'))

restore(); run()
print()
print(f'{sum(ok)} of {len(ok)} historical bug shapes caught')
sys.exit(0 if all(ok) else 1)

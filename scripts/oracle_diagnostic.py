"""Development-only diagnostic behind the oracle table in docs/research-log.md.

Gives the pre-close baseline the variance and VIX of session s-1, which are not
available at its cutoff, and reports how much of the text model's gain survives.
Only target dates through 2023-12-13 are used. Needs the private artifacts and
data/volatility_study.json. Run from the repository root:
    uv run python scripts/oracle_diagnostic.py
"""
import json, glob, numpy as np
from datetime import date
from pathlib import Path
from newsvar.study import volatility as v
import newsvar.cli as cli
settings=json.load(open('data/volatility_study.json')); inp=cli._vol_inputs(settings)
rows=[r for r in v.build_panel(inp) if r['session']<=date(2023,12,13)]; n=len(rows)
cache=sorted(glob.glob('data/derived/text_shares/*.npz'),key=lambda p:Path(p).stat().st_mtime)[-1]
X=np.load(cache)['pre_close'][:n]
for i,r in enumerate(rows):
    nxt=rows[i+1] if i+1<n else None
    r['oracle_d_pre_close']=None if nxt is None else nxt.get('har_d_pre_close')
    r['oracle_vix_pre_close']=None if nxt is None else nxt.get('log_vix_pre_close')
START,END=date(2021,1,4),date(2023,12,13)
def run(tag,base):
    v.BASE_FEATURES['pre_close']=base
    b=v.forecast_all(rows,'pre_close'); t=v.forecast_all(rows,'pre_close',text=X)
    c=v.compare(rows,'pre_close',b,t,start=START,end=END); q=c['qlike']
    print('%-28s base QLIKE %.4f | text gain %+.2f%% t=%.2f p1=%.3f | pin5 %+.2f%% | fz0 %+.4f | n=%d'%(tag,q['baseline_mean'],100*q['relative_gain'],q['diebold_mariano']['statistic'],q['diebold_mariano']['p_value_challenger_better'],100*c['pinball_0.05']['relative_gain'],c['fz0_0.05']['mean_improvement'],c['pairs']))
orig=v.BASE_FEATURES['pre_close']
run('declared baseline',orig)
run('+ same-day variance (oracle)',orig+('oracle_d',))
run('+ same-day variance and VIX',orig+('oracle_d','oracle_vix'))

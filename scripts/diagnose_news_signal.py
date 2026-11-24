"""Exploratory diagnostics behind docs/next-methodology.md.

Uses only rows with target dates up to 2023-12-13 (training and development).
The locked test period is never read. Needs the private artifacts described in
docs/reproduce.md.

Run from the repository root:  uv run python scripts/diagnose_news_signal.py
"""

import json
from datetime import date

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import statsmodels.api as sm
from sklearn.linear_model import QuantileRegressor

CUTOFF = date(2023, 12, 13)
DEVELOPMENT_START = date(2022, 12, 13)
config = json.load(open("data/study.json"))
reg = json.load(open("docs/records/preregistration_20261124.json"))
f=pq.read_table(f"data/derived/features/{reg['feature_table_id']}/features.parquet").to_pandas()
lab=pq.read_table(config['market_dataset']+'/labels.parquet',columns=['origin_session','target_end_session','return_simple']).to_pandas()
d=f.merge(lab[['origin_session','return_simple']],on='origin_session')
same=lab[['target_end_session','return_simple']].rename(columns={'target_end_session':'origin_session','return_simple':'r_same_day'})
d=d.merge(same,on='origin_session',how='left')
d=d[d.eligible & (d.target_end_session<=CUTOFF)].copy().reset_index(drop=True)
dv=d[d.target_end_session>=DEVELOPMENT_START]
print('rows',len(d),len(d)-len(dv),len(dv))
se=(d.sentiment_dispersion/np.sqrt(d.scored_count)); print('median scored',d.scored_count.median(),'median SE of mean',round(se.median(),4),'day-to-day SD of sentiment_mean',round(d.sentiment_mean.std(),4),'SD of first difference',round(d.sentiment_mean.diff().std(),4), 'lag1 autocorr',round(d.sentiment_mean.autocorr(1),3))
for c in ['sentiment_mean','negative_probability_mean','negative_headline_ratio','news_log_rate','news_rate_z63','sentiment_shock21']:
    print(c,'corr same-day r',round(d[c].corr(d.r_same_day),3),'| prev-day r',round(d[c].corr(d.return_last),3),'| next-day r',round(d[c].corr(d.return_simple),3),'| next |r|',round(d[c].corr(d.return_simple.abs()),3),'| vix',round(d[c].corr(d.vix_last),3))
y=np.log(d.return_simple.abs()+1e-4)
base=['vix_last','vol_21','ewma_sigma','abs_return_last']
def fit(cols):
    X=d[cols].fillna(d[cols].median()); X=(X-X.mean())/X.std(); X=sm.add_constant(X)
    return sm.OLS(y,X).fit(cov_type='HAC',cov_kwds={'maxlags':10})
m0=fit(base); print('base R2',round(m0.rsquared,4))
for c in ['news_log_rate','news_rate_z63','sentiment_mean','negative_probability_mean','negative_headline_ratio','sentiment_shock21','negative_log_intensity']:
    m=fit(base+[c]); print(' +',c,'R2',round(m.rsquared,4),'t',round(m.tvalues[c],2))
d['abs_same']=d.r_same_day.abs(); m=fit(base+['abs_same']); print(' + |same-day return| (not in the design) R2',round(m.rsquared,4),'t',round(m.tvalues['abs_same'],2))
m=fit(base+['abs_same','negative_probability_mean']); print(' + both: t neg',round(m.tvalues['negative_probability_mean'],2))
def pin(y,q,a=0.05): return np.mean((a-(y<q))*(y-q))
dv=d[d.target_end_session>=DEVELOPMENT_START]
def ls(cols,pen,scale='ewma_sigma'):
    out=[]
    for _,g in dv.groupby([pd.to_datetime(dv.origin_session).dt.year,pd.to_datetime(dv.origin_session).dt.month]):
        T=d[d.origin_session<g.origin_session.min()].iloc[:-2]
        z=T.return_simple/T[scale]
        if cols:
            A=T[cols].fillna(T[cols].median()); mu,sd=A.mean(),A.std()
            qr=QuantileRegressor(quantile=0.05,alpha=pen,solver='highs').fit(((A-mu)/sd).values,z)
            qz=qr.predict(((g[cols].fillna(T[cols].median())-mu)/sd).values)
        else: qz=np.full(len(g),np.quantile(z,0.05))
        out.append(pd.Series(qz*g[scale].values,index=g.index))
    q=pd.concat(out); return round(pin(dv.return_simple,q)*1e4,3), int((dv.return_simple<q).sum())
print('volatility-scaled quantile, dev pinball bp, breaches (expect 12.5); reference Q0 8.762, GARCH-t 8.851')
for scale in ('ewma_sigma','vix_last'):
    print(' scale',scale,'const',ls([],0,scale))
    for name,cols in [('M',['vix_last','return_last']),('C',['vix_last','return_last','news_rate_z63']),('S',['vix_last','return_last','news_rate_z63','negative_probability_mean','sentiment_shock21'])]:
        for pen in (0.001,0.01): print('  ',name,pen,ls(cols,pen,scale))

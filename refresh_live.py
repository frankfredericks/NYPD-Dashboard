#!/usr/bin/env python3
"""Pull the latest NYPD complaint data from NYC Open Data (Socrata) and write
monthly.json for the dashboard's trailing-12-month / YoY panel.

Datasets:
  Historic (2006 -> end of prior year):  qgea-i56i
  Current  (year to date):               5uac-w243
Fields: cmplnt_fr_dt (date), addr_pct_cd (precinct), law_cat_cd (FELONY/MISDEMEANOR/VIOLATION)

NYC refreshes these roughly quarterly, so run monthly/quarterly; it re-pulls whatever is current.
Optional: set SOCRATA_APP_TOKEN env var to raise rate limits.
"""
import requests, json, datetime, os, collections, sys
BASE='https://data.cityofnewyork.us/resource/{}.json'
HIST='qgea-i56i'; YTD='5uac-w243'
TOKEN=os.environ.get('SOCRATA_APP_TOKEN')
CATMAP={'FELONY':'felony','MISDEMEANOR':'misd','VIOLATION':'viol'}

def q(dataset, since_iso):
    headers={'X-App-Token':TOKEN} if TOKEN else {}
    params={'$select':'date_trunc_ym(cmplnt_fr_dt) as ym, addr_pct_cd, law_cat_cd, count(1) as n',
            '$where':f"cmplnt_fr_dt >= '{since_iso}' AND addr_pct_cd IS NOT NULL",
            '$group':'ym, addr_pct_cd, law_cat_cd','$limit':'200000'}
    r=requests.get(BASE.format(dataset),params=params,headers=headers,timeout=120)
    r.raise_for_status(); return r.json()

def main():
    today=datetime.date.today()
    start=(today.replace(day=1)-datetime.timedelta(days=365*2+40)).replace(day=1)
    since=start.strftime('%Y-%m-%dT00:00:00')
    rows=[]
    for ds in (HIST,YTD):
        try: rows+=q(ds,since)
        except Exception as e: print(f'warn: {ds} fetch failed: {e}',file=sys.stderr)
    # aggregate (ym, pct) -> counts
    agg=collections.defaultdict(lambda: {'total':0,'felony':0,'misd':0,'viol':0})
    for row in rows:
        ym=(row.get('ym') or '')[:7]  # 'YYYY-MM'
        pct=row.get('addr_pct_cd'); cat=CATMAP.get(row.get('law_cat_cd'))
        if not ym or not pct: continue
        try: pct=str(int(float(pct)))
        except: continue
        n=int(float(row.get('n',0)))
        agg[(ym,pct)]['total']+=n
        if cat: agg[(ym,pct)][cat]+=n
    byP=collections.defaultdict(list)
    for (ym,pct),c in agg.items():
        byP[pct].append({'ym':ym,**c})
    for pct in byP: byP[pct].sort(key=lambda x:x['ym'])
    out={'generated':today.isoformat(),'source':'NYPD Complaint Data (qgea-i56i + 5uac-w243)','byPrecinct':byP}
    with open('monthly.json','w') as f: json.dump(out,f,separators=(',',':'))
    print(f'wrote monthly.json — {len(byP)} precincts, {sum(len(v) for v in byP.values())} precinct-months through {max((r["ym"] for v in byP.values() for r in v), default="?")}')

if __name__=='__main__': main()

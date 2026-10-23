#!/usr/bin/env python3
"""Pull the latest NYC Open Data and write the dashboard's live JSON feeds:
  monthly.json          trailing 24 months of complaints, by precinct (12-mo / YoY view)
  shootings.json        shooting incidents by precinct x year (NYPD)
  arrests.json          arrests by precinct x year (NYPD)
  traffic.json          motor-vehicle crashes/injured/killed by precinct x year (ZIP-approximated)
  complaints311.json    top 311 complaint types by precinct, last 12 months (ZIP-approximated)

Precinct-tagged datasets (shootings, arrests, complaints) use the precinct field directly.
Collisions and 311 are NOT precinct-tagged, so they are aggregated by ZIP and allocated to a
precinct with zip_precinct_crosswalk.json (ZIP -> precinct of its centroid; approximate).

Run monthly/quarterly. Optional: set SOCRATA_APP_TOKEN to raise rate limits."""
import requests, json, datetime, os, collections, sys
BASE='https://data.cityofnewyork.us/resource/{}.json'
DS=dict(cmpH='qgea-i56i', cmpY='5uac-w243', shoot='833y-fsy8',
        arrestH='8h9b-rp9u', arrestY='uip8-fykc', collide='h9gi-nx95', c311='erm2-nwe9')
TOKEN=os.environ.get('SOCRATA_APP_TOKEN')
HEAD={'X-App-Token':TOKEN} if TOKEN else {}
HERE=os.path.dirname(os.path.abspath(__file__))
XWALK={str(k):int(v) for k,v in json.load(open(os.path.join(HERE,'zip_precinct_crosswalk.json'))).items()}

def soql(ds, **params):
    try:
        r=requests.get(BASE.format(DS[ds]), params=params, headers=HEAD, timeout=180)
        r.raise_for_status(); return r.json()
    except Exception as e:
        print(f'warn: {ds} fetch failed: {e}', file=sys.stderr); return None

def write(name, obj):
    with open(os.path.join(HERE, name), 'w') as f: json.dump(obj, f, separators=(',',':'))
    print('wrote', name)

def today(): return datetime.date.today()
def iso_months_ago(n):
    d=today().replace(day=1)
    return (d - datetime.timedelta(days=31*n)).replace(day=1).isoformat()

# ---------- monthly complaints (trailing 24 mo) by precinct ----------
def monthly():
    since=iso_months_ago(25)
    rows=[]
    for k in ('cmpH','cmpY'):
        r=soql(k, **{'$select':'date_trunc_ym(cmplnt_fr_dt) as ym, addr_pct_cd, law_cat_cd, count(1) as n',
                     '$where':f"cmplnt_fr_dt >= '{since}T00:00:00' AND addr_pct_cd IS NOT NULL",
                     '$group':'ym, addr_pct_cd, law_cat_cd', '$limit':'200000'})
        if r: rows+=r
    CAT={'FELONY':'felony','MISDEMEANOR':'misd','VIOLATION':'viol'}
    agg=collections.defaultdict(lambda: collections.defaultdict(lambda:{'total':0,'felony':0,'misd':0,'viol':0}))
    for row in rows:
        ym=(row.get('ym') or '')[:7]; p=row.get('addr_pct_cd')
        if not ym or not p: continue
        try: p=str(int(float(p)))
        except: continue
        n=int(float(row.get('n',0))); o=agg[p][ym]; o['total']+=n
        c=CAT.get(row.get('law_cat_cd'));
        if c: o[c]+=n
    byP={p:[dict(ym=ym, **v) for ym,v in sorted(d.items())] for p,d in agg.items()}
    write('monthly.json', {'generated':today().isoformat(),'source':'NYPD Complaint Data','byPrecinct':byP})

# ---------- shootings / arrests by precinct x year ----------
def by_precinct_year(name, datasets, datefield, pctfield, src):
    rows=[]
    for k in datasets:
        r=soql(k, **{'$select':f'date_extract_y({datefield}) as yr, {pctfield} as precinct, count(1) as n',
                     '$group':f'yr, {pctfield}', '$limit':'20000'})
        if r: rows+=r
    byP=collections.defaultdict(lambda: collections.defaultdict(int)); city=collections.defaultdict(int); yrs=set()
    for row in rows:
        try: yr=int(float(row['yr'])); p=int(float(row['precinct'])); n=int(float(row['n']))
        except: continue
        if yr<2000 or yr>today().year: continue
        yrs.add(yr); byP[str(p)][str(yr)]+=n; city[str(yr)]+=n
    write(name, {'generated':today().isoformat(),'source':src,'years':sorted(yrs),
                 'byPrecinct':{p:dict(d) for p,d in byP.items()},'city':dict(city)})

# ---------- collisions -> precinct via ZIP ----------
def traffic():
    r=soql('collide', **{'$select':'date_extract_y(crash_date) as yr, zip_code, count(1) as crashes, '
                         'sum(number_of_persons_injured) as inj, sum(number_of_persons_killed) as kill',
                         '$where':'zip_code IS NOT NULL','$group':'yr, zip_code','$limit':'80000'})
    if not r: return
    byP=collections.defaultdict(lambda: collections.defaultdict(lambda:{'crashes':0,'inj':0,'kill':0}))
    for row in r:
        z=str(row.get('zip_code','')).split('.')[0].zfill(5); p=XWALK.get(z)
        if not p: continue
        try: yr=int(float(row['yr']))
        except: continue
        if yr<2012 or yr>today().year: continue
        o=byP[str(p)][yr]; o['crashes']+=int(float(row.get('crashes',0) or 0))
        o['inj']+=int(float(row.get('inj',0) or 0)); o['kill']+=int(float(row.get('kill',0) or 0))
    out={p:[dict(yr=yr, **v) for yr,v in sorted(d.items())] for p,d in byP.items()}
    write('traffic.json', {'generated':today().isoformat(),'source':'NYC Motor Vehicle Collisions (ZIP-approximated to precinct)','byPrecinct':out})

# ---------- 311 -> precinct via ZIP, top types ----------
def requests311():
    since=iso_months_ago(12)
    r=soql('c311', **{'$select':'incident_zip, complaint_type, count(1) as n',
                      '$where':f"created_date > '{since}T00:00:00' AND incident_zip IS NOT NULL",
                      '$group':'incident_zip, complaint_type','$limit':'400000'})
    if not r: return
    byP=collections.defaultdict(lambda: collections.defaultdict(int))
    for row in r:
        z=str(row.get('incident_zip','')).split('.')[0].zfill(5); p=XWALK.get(z)
        if not p: continue
        byP[str(p)][row.get('complaint_type','Unknown')]+=int(float(row.get('n',0) or 0))
    out={p:[{'type':t,'n':n} for t,n in sorted(d.items(), key=lambda x:-x[1])[:12]] for p,d in byP.items()}
    write('complaints311.json', {'generated':today().isoformat(),'source':'NYC 311 Service Requests (ZIP-approximated to precinct)','byPrecinct':out})

if __name__=='__main__':
    monthly()
    by_precinct_year('shootings.json', ['shoot'], 'occur_date', 'precinct', 'NYPD Shooting Incident Data')
    by_precinct_year('arrests.json', ['arrestH','arrestY'], 'arrest_date', 'arrest_precinct', 'NYPD Arrests Data')
    traffic()
    requests311()
    print('done.')

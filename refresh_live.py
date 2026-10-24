#!/usr/bin/env python3
"""Pull the latest NYC Open Data and write the dashboard's live JSON feeds:
  monthly.json         trailing 24 months of complaints, by precinct (12-mo / YoY view)
  shootings.json       shooting incidents by precinct x year (NYPD)
  arrests.json         arrests by precinct x year (NYPD)
  traffic.json         motor-vehicle crashes/injured/killed by precinct x year (ZIP area-weighted)
  complaints311.json   311 totals + top complaint types by precinct x year (ZIP area-weighted)

Shootings/arrests/complaints use the precinct field directly. Collisions and 311 are not
precinct-tagged, so they are aggregated by ZIP and split across precincts by AREA OVERLAP using
zip_precinct_crosswalk.json  (format: {zip: [[precinct, fraction], ...]}).

Run monthly/quarterly. Optional: set SOCRATA_APP_TOKEN to raise rate limits."""
import requests, json, datetime, os, collections, sys
BASE='https://data.cityofnewyork.us/resource/{}.json'
DS=dict(cmpH='qgea-i56i', cmpY='5uac-w243', shoot='833y-fsy8',
        arrestH='8h9b-rp9u', arrestY='uip8-fykc', collide='h9gi-nx95', c311='erm2-nwe9', shootY='5ucz-vwe8')
TOKEN=os.environ.get('SOCRATA_APP_TOKEN')
HEAD={'X-App-Token':TOKEN} if TOKEN else {}
HERE=os.path.dirname(os.path.abspath(__file__))
XW={str(k):[(int(p),float(f)) for p,f in v] for k,v in json.load(open(os.path.join(HERE,'zip_precinct_crosswalk.json'))).items()}

def soql(ds, **p):
    try:
        r=requests.get(BASE.format(DS[ds]), params=p, headers=HEAD, timeout=300); r.raise_for_status(); return r.json()
    except Exception as e:
        print(f'warn: {ds} fetch failed: {e}', file=sys.stderr); return None

def write(name, obj):
    with open(os.path.join(HERE, name), 'w') as f: json.dump(obj, f, separators=(',',':'))
    print('wrote', name)

def zkey(z):
    try: return str(int(float(z))).zfill(5)
    except: return None

def today(): return datetime.date.today()
def months_ago_iso(n):
    d=today().replace(day=1)
    return (d - datetime.timedelta(days=31*n)).replace(day=1).isoformat()

def monthly():
    since=months_ago_iso(25); rows=[]
    for k in ('cmpH','cmpY'):
        r=soql(k, **{'$select':'date_trunc_ym(cmplnt_fr_dt) as ym, addr_pct_cd, law_cat_cd, count(1) as n',
                     '$where':f"cmplnt_fr_dt >= '{since}T00:00:00' AND addr_pct_cd IS NOT NULL",
                     '$group':'ym, addr_pct_cd, law_cat_cd', '$limit':'300000'})
        if r: rows+=r
    CAT={'FELONY':'felony','MISDEMEANOR':'misd','VIOLATION':'viol'}
    agg=collections.defaultdict(lambda: collections.defaultdict(lambda:{'total':0,'felony':0,'misd':0,'viol':0}))
    for row in rows:
        ym=(row.get('ym') or '')[:7]; p=row.get('addr_pct_cd')
        if not ym or not p: continue
        try: p=str(int(float(p)))
        except: continue
        n=int(float(row.get('n',0))); o=agg[p][ym]; o['total']+=n
        c=CAT.get(row.get('law_cat_cd'))
        if c: o[c]+=n
    byP={p:[dict(ym=ym, **v) for ym,v in sorted(d.items())] for p,d in agg.items()}
    write('monthly.json', {'generated':today().isoformat(),'source':'NYPD Complaint Data','byPrecinct':byP})

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

def traffic():
    r=soql('collide', **{'$select':'date_extract_y(crash_date) as yr, zip_code, count(1) as crashes, '
                         'sum(number_of_persons_injured) as inj, sum(number_of_persons_killed) as kill',
                         '$where':'zip_code IS NOT NULL','$group':'yr, zip_code','$limit':'100000'})
    if not r: return
    byP=collections.defaultdict(lambda: collections.defaultdict(lambda:{'crashes':0.0,'inj':0.0,'kill':0.0}))
    for row in r:
        z=zkey(row.get('zip_code'))
        if not z or z not in XW: continue
        try: yr=int(float(row['yr']))
        except: continue
        if yr<2013 or yr>today().year: continue
        cr=float(row.get('crashes',0) or 0); ij=float(row.get('inj',0) or 0); kl=float(row.get('kill',0) or 0)
        for p,fr in XW[z]:
            o=byP[str(p)][yr]; o['crashes']+=cr*fr; o['inj']+=ij*fr; o['kill']+=kl*fr
    out={p:[{'yr':yr,'crashes':round(v['crashes']),'inj':round(v['inj']),'kill':round(v['kill'],1)}
            for yr,v in sorted(d.items())] for p,d in byP.items()}
    write('traffic.json', {'generated':today().isoformat(),
          'source':'NYC Motor Vehicle Collisions (ZIP area-weighted to precinct)','byPrecinct':out})

def requests311():
    START='2016-01-01'
    top=soql('c311', **{'$select':'complaint_type, count(1) as n',
             '$where':f"created_date > '{months_ago_iso(36)}T00:00:00' AND complaint_type IS NOT NULL",
             '$group':'complaint_type','$order':'n desc','$limit':'12'})
    if not top: return
    topTypes=[t['complaint_type'] for t in top]
    inlist='('+','.join("'"+t.replace("'","''")+"'" for t in topTypes)+')'
    tot=soql('c311', **{'$select':'date_extract_y(created_date) as yr, incident_zip, count(1) as n',
             '$where':f"created_date > '{START}T00:00:00' AND incident_zip IS NOT NULL",
             '$group':'yr, incident_zip','$limit':'200000'})
    typ=soql('c311', **{'$select':'date_extract_y(created_date) as yr, incident_zip, complaint_type, count(1) as n',
             '$where':f"created_date > '{START}T00:00:00' AND incident_zip IS NOT NULL AND complaint_type in {inlist}",
             '$group':'yr, incident_zip, complaint_type','$limit':'500000'})
    if not tot: return
    byP=collections.defaultdict(lambda:{'total':collections.defaultdict(float),'types':collections.defaultdict(lambda:collections.defaultdict(float))})
    city={'total':collections.defaultdict(float),'types':collections.defaultdict(lambda:collections.defaultdict(float))}
    yrs=set()
    for row in tot:
        z=zkey(row.get('incident_zip'))
        if not z or z not in XW: continue
        try: yr=int(float(row['yr']))
        except: continue
        if yr<2016 or yr>today().year: continue
        yrs.add(yr); n=float(row.get('n',0) or 0)
        for p,fr in XW[z]: byP[str(p)]['total'][yr]+=n*fr
        city['total'][yr]+=n
    for row in (typ or []):
        z=zkey(row.get('incident_zip')); ct=row.get('complaint_type')
        if not z or z not in XW or ct not in topTypes: continue
        try: yr=int(float(row['yr']))
        except: continue
        if yr<2016 or yr>today().year: continue
        n=float(row.get('n',0) or 0)
        for p,fr in XW[z]: byP[str(p)]['types'][ct][yr]+=n*fr
        city['types'][ct][yr]+=n
    pt=lambda d:{str(y):round(v) for y,v in d.items()}
    pty=lambda d:{t:{str(y):round(v) for y,v in yr.items()} for t,yr in d.items()}
    write('complaints311.json', {'generated':today().isoformat(),
          'source':'NYC 311 Service Requests (ZIP area-weighted to precinct)',
          'years':sorted(yrs),'topTypes':topTypes,
          'byPrecinct':{p:{'total':pt(v['total']),'types':pty(v['types'])} for p,v in byP.items()},
          'city':{'total':pt(city['total']),'types':pty(city['types'])}})

def safe(fn,*a):
    try: fn(*a)
    except Exception as e: print(f'warn: {getattr(fn,"__name__",fn)} failed: {e}', file=sys.stderr)

if __name__=='__main__':
    safe(monthly)
    safe(by_precinct_year,'shootings.json', ['shoot','shootY'], 'occur_date', 'precinct', 'NYPD Shooting Incident Data')
    safe(by_precinct_year,'arrests.json', ['arrestH','arrestY'], 'arrest_date', 'arrest_precinct', 'NYPD Arrests Data')
    safe(traffic)
    safe(requests311)
    print('done.')

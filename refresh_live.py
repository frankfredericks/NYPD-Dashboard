#!/usr/bin/env python3
"""NYC Precinct Public Safety Dashboard — full data refresh.

Writes static JSON feeds the dashboard loads (so every tab loads instantly instead of querying
NYC Open Data live). Run on a schedule (GitHub Action). Optional env SOCRATA_APP_TOKEN raises limits.

Feeds written (all keyed by precinct):
  Yearly:   shootings.json arrests.json n911.json citations.json  (shape: years/byPrecinct/city)
            traffic.json (crashes/inj/kill)   complaints311.json (totals + top types)
  Monthly:  crime_monthly.json shootings_monthly.json arrests_monthly.json
            traffic_monthly.json c311_monthly.json n911_monthly.json citations_monthly.json
  Pies:     traffic_factors.json n911_types.json
  Waits:    wait311.json (avg days to close, precinct x year)   [911 response time deferred]

Collisions & 311 are not precinct-tagged -> area-weighted from ZIP via zip_precinct_crosswalk.json.
"""
import requests, json, datetime, os, collections, sys
BASE='https://data.cityofnewyork.us/resource/{}.json'
DS=dict(cmpH='qgea-i56i', cmpY='5uac-w243', shoot='833y-fsy8', shootY='5ucz-vwe8',
        arrestH='8h9b-rp9u', arrestY='uip8-fykc', collide='h9gi-nx95', c311='erm2-nwe9',
        cadH='d6zx-ckhd', cadY='n2zq-pubd', bsumH='bme5-7ty4', bsumY='57p3-pdcj')
TOKEN=os.environ.get('SOCRATA_APP_TOKEN'); HEAD={'X-App-Token':TOKEN} if TOKEN else {}
HERE=os.path.dirname(os.path.abspath(__file__))
XW={str(k):[(int(p),float(f)) for p,f in v] for k,v in json.load(open(os.path.join(HERE,'zip_precinct_crosswalk.json'))).items()}
TODAY=datetime.date.today()

def soql(ds, **p):
    try:
        r=requests.get(BASE.format(DS[ds]), params=p, headers=HEAD, timeout=600); r.raise_for_status(); return r.json()
    except Exception as e:
        print(f'warn: {ds} fetch failed: {e}', file=sys.stderr); return None
def write(name, obj):
    with open(os.path.join(HERE,name),'w') as f: json.dump(obj,f,separators=(',',':'))
    print('wrote',name)
def zkey(z):
    try: return str(int(float(z))).zfill(5)
    except: return None
def months_ago(n):
    d=TODAY.replace(day=1)
    return (d-datetime.timedelta(days=31*n)).replace(day=1).isoformat()
G='generated'

# ---------- generic yearly: precinct x year counts ----------
def byyear(name, datasets, datefield, pctfield, src, ymin=2000):
    rows=[]
    for k in datasets:
        r=soql(k, **{'$select':f'date_extract_y({datefield}) as yr, {pctfield} as precinct, count(1) as n',
                     '$group':f'yr, {pctfield}','$limit':'30000'})
        print(f'  byyear {name}: dataset {k} -> {len(r) if r else 0} rows', flush=True)
        if r: rows+=r
    byP=collections.defaultdict(lambda: collections.defaultdict(int)); city=collections.defaultdict(int); yrs=set()
    for row in rows:
        try: yr=int(float(row['yr'])); p=int(float(row['precinct'])); n=int(float(row['n']))
        except: continue
        if yr<ymin or yr>TODAY.year: continue
        yrs.add(yr); byP[str(p)][str(yr)]+=n; city[str(yr)]+=n
    write(name, {G:TODAY.isoformat(),'source':src,'years':sorted(yrs),'byPrecinct':{p:dict(d) for p,d in byP.items()},'city':dict(city)})

# ---------- generic monthly: precinct x month counts ----------
def bymonth(name, datasets, datefield, pctfield, src):
    since=months_ago(15); rows=[]
    for k in datasets:
        r=soql(k, **{'$select':f'date_trunc_ym({datefield}) as ym, {pctfield} as precinct, count(1) as n',
                     '$where':f"{datefield} > '{since}T00:00:00' AND {pctfield} IS NOT NULL",
                     '$group':f'ym, {pctfield}','$limit':'40000'})
        if r: rows+=r
    byP=collections.defaultdict(lambda: collections.defaultdict(int)); ms=set()
    for row in rows:
        ym=(row.get('ym') or '')[:7]
        try: p=int(float(row['precinct'])); n=int(float(row['n']))
        except: continue
        if not ym: continue
        ms.add(ym); byP[str(p)][ym]+=n
    write(name, {G:TODAY.isoformat(),'source':src,'months':sorted(ms),'byP':{p:dict(d) for p,d in byP.items()}})

# ---------- monthly via ZIP area-weighting ----------
def bymonth_zip(name, ds, datefield, zipfield, src):
    since=months_ago(15)
    r=soql(ds, **{'$select':f'date_trunc_ym({datefield}) as ym, {zipfield} as zip, count(1) as n',
                  '$where':f"{datefield} > '{since}T00:00:00' AND {zipfield} IS NOT NULL",
                  '$group':f'ym, {zipfield}','$limit':'200000'})
    if not r: return
    byP=collections.defaultdict(lambda: collections.defaultdict(float)); ms=set()
    for row in r:
        ym=(row.get('ym') or '')[:7]; z=zkey(row.get('zip'))
        if not ym or not z or z not in XW: continue
        ms.add(ym); n=float(row.get('n',0) or 0)
        for p,fr in XW[z]: byP[str(p)][ym]+=n*fr
    write(name, {G:TODAY.isoformat(),'source':src,'months':sorted(ms),'byP':{p:{m:round(v) for m,v in d.items()} for p,d in byP.items()}})

# ---------- crime monthly (categories: law class + 7 major ky) ----------
def crime_monthly():
    since=months_ago(15)
    qc=lambda d: soql(d, **{'$select':'date_trunc_ym(cmplnt_fr_dt) as ym, addr_pct_cd as pct, law_cat_cd, count(1) as n',
                            '$where':f"cmplnt_fr_dt > '{since}T00:00:00' AND addr_pct_cd IS NOT NULL",
                            '$group':'ym, addr_pct_cd, law_cat_cd','$limit':'60000'})
    qk=lambda d: soql(d, **{'$select':'date_trunc_ym(cmplnt_fr_dt) as ym, addr_pct_cd as pct, ky_cd, count(1) as n',
                            '$where':f"cmplnt_fr_dt > '{since}T00:00:00' AND addr_pct_cd IS NOT NULL AND ky_cd in (101,104,105,106,107,109,110)",
                            '$group':'ym, addr_pct_cd, ky_cd','$limit':'60000'})
    c1,c2,k1,k2=qc('cmpH'),qc('cmpY'),qk('cmpH'),qk('cmpY')
    if not c1 and not c2: return
    M=collections.defaultdict(dict); ms=set()
    def cell(p,ym):
        d=M[str(p)].setdefault(ym,{'total':0,'felony':0,'misd':0,'viol':0,'k101':0,'k104':0,'k105':0,'k106':0,'k107':0,'k109':0,'k110':0}); return d
    for r in (c1 or [])+(c2 or []):
        ym=(r.get('ym') or '')[:7]
        try: p=int(float(r['pct'])); n=int(float(r['n']))
        except: continue
        if not ym: continue
        ms.add(ym); o=cell(p,ym); o['total']+=n; c=r.get('law_cat_cd')
        if c=='FELONY': o['felony']+=n
        elif c=='MISDEMEANOR': o['misd']+=n
        elif c=='VIOLATION': o['viol']+=n
    for r in (k1 or [])+(k2 or []):
        ym=(r.get('ym') or '')[:7]
        try: p=int(float(r['pct'])); key='k'+str(int(float(r['ky_cd']))); n=int(float(r['n']))
        except: continue
        if not ym or key not in ('k101','k104','k105','k106','k107','k109','k110'): continue
        cell(p,ym)[key]+=n
    write('crime_monthly.json', {G:TODAY.isoformat(),'months':sorted(ms),'M':M})

# ---------- collisions: yearly + monthly + factor pie (ZIP weighted) ----------
def traffic():
    r=soql('collide', **{'$select':'date_extract_y(crash_date) as yr, zip_code, count(1) as crashes, sum(number_of_persons_injured) as inj, sum(number_of_persons_killed) as kill',
                         '$where':'zip_code IS NOT NULL','$group':'yr, zip_code','$limit':'100000'})
    if r:
        byP=collections.defaultdict(lambda: collections.defaultdict(lambda:{'crashes':0.0,'inj':0.0,'kill':0.0}))
        for row in r:
            z=zkey(row.get('zip_code'));
            if not z or z not in XW: continue
            try: yr=int(float(row['yr']))
            except: continue
            if yr<2013 or yr>TODAY.year: continue
            cr=float(row.get('crashes',0) or 0); ij=float(row.get('inj',0) or 0); kl=float(row.get('kill',0) or 0)
            for p,fr in XW[z]:
                o=byP[str(p)][yr]; o['crashes']+=cr*fr; o['inj']+=ij*fr; o['kill']+=kl*fr
        out={p:[{'yr':yr,'crashes':round(v['crashes']),'inj':round(v['inj']),'kill':round(v['kill'],1)} for yr,v in sorted(d.items())] for p,d in byP.items()}
        write('traffic.json', {G:TODAY.isoformat(),'source':'NYC Collisions (ZIP area-weighted)','byPrecinct':out})
    bymonth_zip('traffic_monthly.json', 'collide', 'crash_date', 'zip_code', 'NYC Collisions')
    # factor pie (last 12 mo)
    since=months_ago(12)
    r=soql('collide', **{'$select':'zip_code, contributing_factor_vehicle_1 as t, count(1) as n',
           '$where':f"crash_date > '{since}T00:00:00' AND zip_code IS NOT NULL AND contributing_factor_vehicle_1 IS NOT NULL AND contributing_factor_vehicle_1 NOT IN('Unspecified','Does Not Apply')",
           '$group':'zip_code, contributing_factor_vehicle_1','$limit':'200000'})
    if r:
        byP=collections.defaultdict(lambda: collections.defaultdict(float))
        for row in r:
            z=zkey(row.get('zip_code')); t=row.get('t')
            if not z or z not in XW or not t: continue
            n=float(row.get('n',0) or 0)
            for p,fr in XW[z]: byP[str(p)][t]+=n*fr
        out={p:[{'t':t,'n':round(n)} for t,n in sorted(d.items(),key=lambda x:-x[1])[:8]] for p,d in byP.items()}
        write('traffic_factors.json', {G:TODAY.isoformat(),'byPrecinct':out})

# ---------- 311: yearly totals+types + monthly + resolution time (ZIP weighted) ----------
def c311():
    START='2016-01-01'
    top=soql('c311', **{'$select':'complaint_type, count(1) as n','$where':f"created_date > '{months_ago(36)}T00:00:00' AND complaint_type IS NOT NULL",'$group':'complaint_type','$order':'n desc','$limit':'12'})
    if top:
        topTypes=[t['complaint_type'] for t in top]
        inlist='('+','.join("'"+t.replace("'","''")+"'" for t in topTypes)+')'
        tot=soql('c311', **{'$select':'date_extract_y(created_date) as yr, incident_zip, count(1) as n','$where':f"created_date > '{START}T00:00:00' AND incident_zip IS NOT NULL",'$group':'yr, incident_zip','$limit':'200000'})
        typ=soql('c311', **{'$select':'date_extract_y(created_date) as yr, incident_zip, complaint_type, count(1) as n','$where':f"created_date > '{START}T00:00:00' AND incident_zip IS NOT NULL AND complaint_type in {inlist}",'$group':'yr, incident_zip, complaint_type','$limit':'500000'})
        if tot:
            byP=collections.defaultdict(lambda:{'total':collections.defaultdict(float),'types':collections.defaultdict(lambda:collections.defaultdict(float))})
            city={'total':collections.defaultdict(float),'types':collections.defaultdict(lambda:collections.defaultdict(float))}; yrs=set()
            for row in tot:
                z=zkey(row.get('incident_zip'));
                if not z or z not in XW: continue
                try: yr=int(float(row['yr']))
                except: continue
                if yr<2016 or yr>TODAY.year: continue
                yrs.add(yr); n=float(row.get('n',0) or 0)
                for p,fr in XW[z]: byP[str(p)]['total'][yr]+=n*fr
                city['total'][yr]+=n
            for row in (typ or []):
                z=zkey(row.get('incident_zip')); ct=row.get('complaint_type')
                if not z or z not in XW or ct not in topTypes: continue
                try: yr=int(float(row['yr']))
                except: continue
                if yr<2016: continue
                n=float(row.get('n',0) or 0)
                for p,fr in XW[z]: byP[str(p)]['types'][ct][yr]+=n*fr
                city['types'][ct][yr]+=n
            pt=lambda d:{str(y):round(v) for y,v in d.items()}; pty=lambda d:{t:{str(y):round(v) for y,v in yr.items()} for t,yr in d.items()}
            write('complaints311.json', {G:TODAY.isoformat(),'years':sorted(yrs),'topTypes':topTypes,
                  'byPrecinct':{p:{'total':pt(v['total']),'types':pty(v['types'])} for p,v in byP.items()},
                  'city':{'total':pt(city['total']),'types':pty(city['types'])}})
    bymonth_zip('c311_monthly.json', 'c311', 'created_date', 'incident_zip', 'NYC 311')

def wait311():
    r=soql('c311', **{'$select':'date_extract_y(created_date) as yr, incident_zip, avg(date_diff_d(created_date, closed_date)) as avgdays, count(1) as n',
           '$where':f"created_date > '2018-01-01T00:00:00' AND closed_date IS NOT NULL AND incident_zip IS NOT NULL",
           '$group':'yr, incident_zip','$limit':'200000'})
    if r:
        # weight each zip's avg by its count, allocate to precincts
        num=collections.defaultdict(lambda: collections.defaultdict(float)); den=collections.defaultdict(lambda: collections.defaultdict(float))
        cnum=collections.defaultdict(float); cden=collections.defaultdict(float); yrs=set()
        for row in r:
            z=zkey(row.get('incident_zip'))
            try: yr=int(float(row['yr'])); a=float(row['avgdays']); n=float(row.get('n',0) or 0)
            except: continue
            if not z or z not in XW or a<0 or a>400: continue
            yrs.add(yr)
            for p,fr in XW[z]:
                num[str(p)][yr]+=a*n*fr; den[str(p)][yr]+=n*fr
            cnum[yr]+=a*n; cden[yr]+=n
        byP={p:{str(yr):round(num[p][yr]/den[p][yr],1) for yr in num[p] if den[p][yr]} for p in num}
        city={str(yr):round(cnum[yr]/cden[yr],1) for yr in cnum if cden[yr]}
        write('wait311.json', {G:TODAY.isoformat(),'source':'NYC 311 avg days to close (all agencies)','years':sorted(yrs),'byPrecinct':byP,'city':city})

# ---------- 911 call-type pie ----------
def n911_pie():
    since=months_ago(12)
    rows=[]
    for k in ('cadH', 'cadY'):
        r=soql(k, **{'$select':'nypd_pct_cd as pct, typ_desc as t, count(1) as n','$where':f"create_date > '{since}T00:00:00' AND nypd_pct_cd IS NOT NULL AND typ_desc IS NOT NULL",'$group':'nypd_pct_cd, typ_desc','$limit':'60000'})
        if r: rows+=r
    if not rows: return
    byP=collections.defaultdict(lambda: collections.defaultdict(float))
    for row in rows:
        try: p=int(float(row['pct'])); n=float(row.get('n',0) or 0)
        except: continue
        byP[str(p)][row.get('t')]+=n
    out={p:[{'t':t,'n':round(n)} for t,n in sorted(d.items(),key=lambda x:-x[1])[:8]] for p,d in byP.items()}
    write('n911_types.json', {G:TODAY.isoformat(),'byPrecinct':out})

def safe(fn,*a):
    try: fn(*a)
    except Exception as e: print(f'warn: {getattr(fn,"__name__",fn)} failed: {e}', file=sys.stderr)

if __name__=='__main__':
    safe(byyear,'shootings.json',['shoot','shootY'],'occur_date','precinct','NYPD Shootings',2006)
    safe(byyear,'arrests.json',['arrestH','arrestY'],'arrest_date','arrest_precinct','NYPD Arrests',2006)
    safe(byyear,'n911.json',['cadH','cadY'],'create_date','nypd_pct_cd','NYPD 911 Calls for Service',2018)
    safe(byyear,'citations.json',['bsumH','bsumY'],'violation_date','rpt_owning_cmd','NYPD Moving Violation B Summons',2018)
    safe(bymonth,'shootings_monthly.json',['shoot','shootY'],'occur_date','precinct','NYPD Shootings')
    safe(bymonth,'arrests_monthly.json',['arrestH','arrestY'],'arrest_date','arrest_precinct','NYPD Arrests')
    safe(bymonth,'n911_monthly.json',['cadH','cadY'],'create_date','nypd_pct_cd','NYPD 911 Calls')
    safe(bymonth,'citations_monthly.json',['bsumH','bsumY'],'violation_date','rpt_owning_cmd','NYPD B Summons')
    safe(crime_monthly)
    safe(traffic)
    safe(c311)
    safe(wait311)
    safe(n911_pie)
    print('done.')

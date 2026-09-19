"""Live, resumable catalogue estimate audit; never creates jobs or downloads.

Unknown catalogue bounds use a labelled probe, not inferred coverage. Run only
with authorization to query the configured GeoForge Database service.
"""
import concurrent.futures
from collections import Counter
from datetime import date, timedelta
import json
from pathlib import Path
import time
import os

from kiss_cli import obs_access as obs, obs_subset

ROOT = Path(os.environ.get('GEO_SUBSET_TEST_ROOT','output/geodata-subset-audit-2026-09-14')).resolve()
PRIORITY = ['china_dem_90m','dem_china_90m','hwsd_global','hwsd_china','avhrr_landcover',
            'hwsd_global_raster','hwsd_raster','dtb_china','dtb_china_100m','soilgrids_global',
            'clcd_china_land_cover','vic_global_params','cama_glb_15min','cmfd_china_daily_010']


def request_for(d):
    box = d.get('bbox')
    known = isinstance(box,list) and len(box)==4
    if known:
        x=(box[0]+box[2])/2; y=(box[1]+box[3])/2
        bbox=[max(-180,x-.05),max(-90,y-.05),min(180,x+.05),min(90,y+.05)]
    else:
        bbox=[115,37,115.1,37.1]
    body={'dataset_id':d['id'],'bbox':bbox,'variables':[]}
    if d['id'].startswith('cmfd_china_'):
        body.update(variables=['prec'],start='1989-01-01',end='1989-01-07')
    else:
        try:
            start=date.fromisoformat(str(d.get('start_date'))[:10])
            body.update(start=str(start),end=str(start+timedelta(days=6)))
        except ValueError: pass
    return body, 'catalogue-centre probe' if known else 'unlocated North-China probe'


def probe(d):
    body,scope=request_for(d)
    result={'dataset_id':d['id'],'format':d.get('format'),'dataset_kind':d.get('dataset_kind'),
            'request':body,'scope':scope,'checked_at':time.time()}
    try:
        raw=obs.Client(timeout=20)._json('/subsets/estimate',method='POST',body=body)
        result['estimate']={k:v for k,v in raw.items() if k in obs_subset.PUBLIC | {'selection_empty','n_selected_cells','reason'}}
        result['result']='subsettable' if raw.get('subsettable') is True else 'not_subsettable' if raw.get('subsettable') is False else 'invalid_response'
    except obs.ObsAccessError as e:
        result.update(result='request_failed',http_status=e.status,error=e.code)
    except Exception as e:
        result.update(result='client_error',error=type(e).__name__)
    time.sleep(.2)
    return result


def main():
    ds=(obs.load_catalogue() or {}).get('datasets',[])
    if not ds: raise RuntimeError('No catalogue cached')
    if os.environ.get('GEO_SUBSET_RETEST_FROM'):
        previous=json.loads(Path(os.environ['GEO_SUBSET_RETEST_FROM']).read_text())
        selected={i['dataset_id'] for i in previous['items'] if i['result']!='not_subsettable'}
        selected.update(PRIORITY)
        ds=[d for d in ds if d['id'] in selected]
    ds=sorted(ds,key=lambda d: (PRIORITY.index(d['id']) if d['id'] in PRIORITY else 100,d['id']))
    ROOT.mkdir(parents=True,exist_ok=True)
    report_path=ROOT/'estimates.json'
    report=json.loads(report_path.read_text()) if report_path.exists() else {'catalogue_total':len(ds),'items':[]}
    if os.environ.get('GEO_SUBSET_RETRY_ERRORS'):
        obs._atomic_json(ROOT/'estimates-before-retry.json',report)
        report['items']=[i for i in report['items'] if i['result']!='request_failed']
    completed={d['dataset_id'] for d in report['items']}
    obs.token()  # load once, never print credentials
    failures=0
    with concurrent.futures.ThreadPoolExecutor(max_workers=int(os.environ.get('GEO_SUBSET_AUDIT_WORKERS','1'))) as pool:
        pending={pool.submit(probe,d):d['id'] for d in ds if d['id'] not in completed}
        for future in concurrent.futures.as_completed(pending):
            result=future.result();report['items'].append(result)
            report['counts']=dict(Counter(i['result'] for i in report['items']))
            obs._atomic_json(report_path,report)
            failures=failures+1 if result.get('http_status') in (502,503,504) or result.get('error')=='network_error' else 0
            if failures>=3:
                for queued in pending:queued.cancel()
                print('PAUSED: three consecutive service/network failures',flush=True)
                break
            if len(report['items'])%25==0 or result['dataset_id'] in PRIORITY:
                print(len(report['items']),result['dataset_id'],result['result'],result.get('http_status'),report['counts'],flush=True)
    print('COMPLETE',len(report['items']),report['counts'],flush=True)


if __name__=='__main__':main()

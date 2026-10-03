"""Small live query comparison; never writes media or production provider health."""
from __future__ import annotations
import argparse
import dataclasses
import hashlib
import json
import re
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from emby_theme_worker.cli import make_worker
from emby_theme_worker.config import Config
from emby_theme_worker.db import StateDB
from emby_theme_worker.models import Candidate
from emby_theme_worker.providers import Providers
from emby_theme_worker.scoring import normalize, score_all
from emby_theme_worker.security import configure_logging

TEMPLATES = ['{title} theme','{title} main title','{title} main theme','{title} music',
             '{title} soundtrack','{title} {year} main theme','{title} end credits','{local} 主题曲','{title} main']
SOURCES = ['youtube','bilibili','netease','qqmusic','archive','televisiontunes']

def relevance(candidate, item):
    evidence=normalize(candidate.title+' '+str(candidate.metadata.get('album_title') or ''))
    title=normalize(candidate.title)
    channel=normalize(candidate.metadata.get('channel'))
    work=any(normalize(t) in evidence for t in [item.name,item.original_title,*item.aliases] if t)
    composer=bool(re.search(r'hans zimmer|lisa gerrard|汉斯.{0,3}季默',evidence+' '+channel))
    # Reviewed Gladiator reference tracks. Do not treat every same-name album or
    # rapper's song as a film match; this rubric is specific to this benchmark.
    known_track=bool(re.search(r'now we are free|honor him|the battle|duduk of the north|progeny|elysium|the wheat',evidence))
    film_semantics=bool(re.search(r'\b(theme|soundtrack|main title|main titles|opening|credits|ost)\b|主题曲|原声',title))
    related=(work and (film_semantics or composer or known_track)) or (composer and known_track)
    wrong=bool(re.search(r'\b(video game|gameplay|xbox|playstation|gladiator 2|gladiator ii|2024|2025)\b',evidence))
    alternate=bool(re.search(r'\b(cover|remix|live|arr|arranged|trailer|karaoke|reaction|waltz|guitar|piano|epic version|maksim|watazu|relax|study|sleep|classics)\b|翻唱|混剪|现场',evidence))
    compilation=bool(candidate.duration and candidate.duration>900)
    original=composer and known_track and not alternate and not compilation
    return {'related':related and not wrong,'wrong_work':wrong,'alternate_version':alternate,'compilation':compilation,'original_likely':original}

def annotate(row, item):
    for value in row['candidates']:
        value['labels']=relevance(Candidate(value['provider'],value['title'],'unused',duration=value['duration'],metadata=value['evidence']),item)
    values=row['candidates']
    row['p_at_3']=sum(c['labels']['related'] for c in values[:3])/3
    row['clean_at_3']=sum(c['labels']['related'] and not c['labels']['alternate_version'] and not c['labels']['compilation'] for c in values[:3])/3
    row['original_at_3']=sum(c['labels']['related'] and c['labels']['original_likely'] for c in values[:3])/3
    row['related_at_10']=sum(c['labels']['related'] for c in values)
    row['utility']=round(40*row['p_at_3']+25*row['clean_at_3']+25*row['original_at_3']+row['related_at_10'],2)

def recommend_templates(rows, k=3):
    remaining=[r for r in rows if r['outcome']=='hit' and r['p_at_3']>=2/3 and r['utility']>0]
    chosen=[];seen=set()
    while remaining and len(chosen)<k:
        def marginal(row):
            useful={v['source_hash'] for v in row['candidates'] if v['labels']['related'] and not v['labels']['compilation']}
            novelty=len(useful-seen)/max(1,len(useful))
            return row['utility']*(.6+.4*novelty),-row['seconds']
        options=remaining
        # Keep both original-name and localized-name queries when both worked.
        if len(chosen)==1:
            other='{title}' if '{local}' in chosen[0]['template'] else '{local}'
            options=[r for r in remaining if other in r['template']] or remaining
        best=max(options,key=marginal);chosen.append(best);remaining.remove(best)
        seen.update(v['source_hash'] for v in best['candidates'] if v['labels']['related'])
    return [r['template'] for r in chosen]

def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--item',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--search-only',action='store_true')
    parser.add_argument('--sources',default=','.join(SOURCES))
    parser.add_argument('--query-template',action='append')
    args=parser.parse_args(argv)
    configure_logging()
    config=Config.load('/config/config.yaml');db=StateDB(config.database_path)
    worker=make_worker(config,db); item=worker.emby.get_item(args.item)
    if normalize(item.original_title)!='gladiator' or item.year!=2000:
        worker.close();parser.error('this reviewed rubric is specific to Gladiator (2000)')
    sources=args.sources.split(',')
    if any(s not in SOURCES for s in sources):
        worker.close();parser.error('unsupported benchmark source')
    templates=args.query_template or TEMPLATES
    providers=Providers(config.providers.enabled,12,2,db,config.providers.cookies,30)
    results=[]; raw={}
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    def perform(source,template):
        query=template.format(title=item.original_title or item.name,local=item.name,year=item.year or '').strip()
        started=time.monotonic()
        row={'provider':source,'template':template,'query':query}
        try:
            candidates=getattr(providers,source)(dataclasses.replace(item,search_text=query))
            row.update(outcome='hit' if candidates else 'no_result',count=len(candidates),seconds=round(time.monotonic()-started,2),
                       candidates=[{**c.public_dict(),'source_hash':hashlib.sha256(c.source_url.encode()).hexdigest(),'labels':relevance(c,item)} for c in candidates[:10]])
            raw[source,template]=candidates
        except Exception as exc:
            status=getattr(getattr(exc,'response',None),'status_code',None)
            blocked=status in {401,403,429} or type(exc).__name__ in {'ProviderBlocked','YtDlpServiceError'}
            row.update(outcome='blocked' if blocked else 'request_failed',error=type(exc).__name__,http_status=status,seconds=round(time.monotonic()-started,2),count=0,candidates=[])
        values=row['candidates']
        row['p_at_3']=sum(c['labels']['related'] for c in values[:3])/3
        row['clean_at_3']=sum(c['labels']['related'] and not c['labels']['alternate_version'] and not c['labels']['compilation'] for c in values[:3])/3
        row['original_at_3']=sum(c['labels']['related'] and c['labels']['original_likely'] for c in values[:3])/3
        row['related_at_10']=sum(c['labels']['related'] for c in values)
        row['utility']=round(40*row['p_at_3']+25*row['clean_at_3']+25*row['original_at_3']+10*row['related_at_10']/10,2)
        return row
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(perform,s,t) for t in templates for s in sources]
            for future in as_completed(futures):
                row=future.result();results.append(row)
                output.write_text(json.dumps({'item':{'title':item.original_title,'local':item.name,'year':item.year},'rows':results},ensure_ascii=False,indent=2))
                print(json.dumps({k:row[k] for k in ['provider','query','outcome','p_at_3','clean_at_3','utility']},ensure_ascii=False),flush=True)
        ranking={s:sorted((r for r in results if r['provider']==s),key=lambda r:(-r['utility'],r['seconds'])) for s in sources}
        downloads=[]
        for source in ([] if args.search_only else sources):
            seen=set();attempts=0
            for row in ranking[source]:
                candidates=sorted(score_all(raw.get((source,row['template']),[]),item),key=lambda c:(relevance(c,item)['original_likely'],not relevance(c,item)['alternate_version'],c.score),reverse=True)
                for candidate in candidates:
                    if not relevance(candidate,item)['related'] or candidate.source_url in seen:continue
                    seen.add(candidate.source_url);attempts+=1
                    result={'provider':source,'title':candidate.title,'template':row['template'],'source_hash':hashlib.sha256(candidate.source_url.encode()).hexdigest()}
                    try:
                        with tempfile.TemporaryDirectory(prefix='theme-query-benchmark-') as temporary:
                            downloaded=worker.audio.fetch_candidate(candidate,Path(temporary))
                            result['audio']=worker.audio.validate_source(downloaded)
                        result['outcome']='downloaded'
                    except Exception as exc:result.update(outcome='download_failed',error=type(exc).__name__)
                    downloads.append(result)
                    print(json.dumps({k:v for k,v in result.items() if k!='audio'},ensure_ascii=False),flush=True)
                    break
                if attempts:break # one transport check per source; not a batch downloader
        report={'item':{'title':item.original_title,'local':item.name,'year':item.year},'rows':results,'downloads':downloads,
                'ranking':{s:[{'template':r['template'],'utility':r['utility'],'p_at_3':r['p_at_3'],'count':r['count']} for r in rows] for s,rows in ranking.items()},
                'label_method':'Strict work-title/album matching, conflict and alternate-version filters; labels need title review, not a user listening verdict.'}
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    finally:providers.close();worker.close()

if __name__=='__main__':main()

"""按来源、业务日期和采集范围组织指标，保留全部组成引用。"""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from ..contracts import canonical, instant
from ..metric_rules import sum_field, when
from .contracts import ContentBlock
from .reading import content, fields_block, ref

PROCESSOR = 'metric-day-v1'
PROFILE_VERSION = 1
KINDS = ('traffic_hourly',)


def accepts(row): return row['kind'] in KINDS

def header(row, scope=None): return 'metric_day', {'traffic_hourly': 'network_day'}[row['kind']]


def zone(row):
    return row['normalized'].get('source_timezone', row['timezone'])


def scopes(row):
    kind = row['kind']; z = zone(row)
    days = [instant(row['occurred_at']).astimezone(ZoneInfo(z)).date().isoformat()] if row['occurred_at'] else []
    measurement = [row['normalized'].get(k) for k in ('measurement_scope', 'measurement_point', 'device_id', 'collector_id')] if kind == 'traffic_hourly' else []
    return [canonical([kind, z, day, measurement]) for day in days] or [canonical([kind,z,None,measurement,row['id']])]


def process_scope(rows, scope_key):
    if not rows: return None
    kind,z,day,measurement,*_ = json.loads(scope_key)
    rows = sorted(rows, key=lambda r: (instant(r['observed_at']), r['id']))
    row = rows[0]; typ,variant = header(row); blocks = []; values = []
    details = {'business_date': day, 'timezone': z, 'started_at': datetime.fromisoformat(day).replace(tzinfo=ZoneInfo(z)).isoformat() if day and z != 'unknown' else None,
               'origin': 'deterministic_projection', 'missing_is_zero': False, 'measurement_scope': measurement, 'composition_in_blocks': True, 'record_count': len(rows)}
    # Source identity already fixes hour+destination+process+route; input updates replace each cumulative grain.
    for r in rows:
        n=r['normalized']; raw=r['raw']
        data={k:raw.get(k) for k in ('bucket','host','process','exit_node','rule','category')}
        data.update({k:n.get(k) for k in ('upload_bytes','download_bytes')})
        blocks.append(fields_block(r,data,key='traffic:'+r['id'],field='raw'))
    values=[{'metric':key,'value':sum_field([r['normalized'] for r in rows],key),'unit':'bytes'} for key in ('upload_bytes','download_bytes')]
    details.update(aggregation='latest_cumulative_per_hour_grain',combine_sources=False); title='网络用量 · '+ str(day or '日期未取得')
    details['metrics']=values
    return content(row,typ,variant,title,blocks,details,coverage={'body':'complete','measurement':'collected_samples_only'})

"""按来源、业务日期和采集范围组织指标，保留全部组成引用。"""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from ..contracts import canonical, instant
from ..metric_rules import HEALTH, finance_totals, health_samples, health_value, sum_field, when
from .contracts import ContentBlock
from .reading import content, fields_block, ref

PROCESSOR = 'metric-day-v1'
PROFILE_VERSION = 1
KINDS = ('health_payloads', 'bill')


def accepts(row): return row['kind'] in KINDS

def header(row, scope=None): return 'metric_day', {'health_payloads': 'health_day', 'bill': 'finance_day'}[row['kind']]


def zone(row):
    return row['normalized'].get('source_timezone', row['timezone'])


def scopes(row):
    kind = row['kind']; z = zone(row)
    if kind == 'health_payloads':
        samples = health_samples(row['normalized']['payload'])
        days = sorted({(when(s.get('day_time')) or when(s['time'])).astimezone(ZoneInfo(z)).date().isoformat() for values in samples.values() for _,s in values})
    else: days = [instant(row['occurred_at']).astimezone(ZoneInfo(z)).date().isoformat()] if row['occurred_at'] else []
    return [canonical([kind, z, day, []]) for day in days] or [canonical([kind,z,None,[],row['id']])]


def process_scope(rows, scope_key):
    if not rows: return None
    kind,z,day,measurement,*_ = json.loads(scope_key)
    rows = sorted(rows, key=lambda r: (instant(r['observed_at']), r['id']))
    row = rows[0]; typ,variant = header(row); blocks = []; values = []
    details = {'business_date': day, 'timezone': z, 'started_at': datetime.fromisoformat(day).replace(tzinfo=ZoneInfo(z)).isoformat() if day and z != 'unknown' else None,
               'origin': 'deterministic_projection', 'missing_is_zero': False, 'measurement_scope': measurement, 'composition_in_blocks': True, 'record_count': len(rows)}
    if kind == 'health_payloads':
        gathered = {key:{} for key in HEALTH}
        for r in rows:
            for key,samples in health_samples(r['normalized']['payload']).items():
                for index,sample in samples:
                    if (when(sample.get('day_time')) or when(sample['time'])).astimezone(ZoneInfo(z)).date().isoformat() != day: continue
                    identity = (sample['time'], sample['origin'], sample['device'])
                    previous = gathered[key].get(identity)
                    references = (previous[1] if previous else []) + [ref(r, f'normalized.payload.{key}[{index}]')]
                    gathered[key][identity] = (sample,references)
        for key, entries in gathered.items():
            samples = [s for s,_ in entries.values()]; value = health_value(key,samples)
            result = {'metric': key, 'label': HEALTH[key][3], 'unit': HEALTH[key][2], 'method': HEALTH[key][4], 'value': value, 'sample_count': len(samples)}
            if key == 'heart_rate' and samples: result.update(min=min(s['value'] for s in samples), max=max(s['value'] for s in samples))
            values.append(result)
            for index,(sample,refs) in enumerate(entries.values()):
                blocks.append(ContentBlock(f'{key}:{index}', 'measurement', f"{result['label']}：{sample['value']} · {sample['time']}", refs, dict(sample, metric=key, source_unit='秒' if key in ('sleep','exercise') else result['unit'])))
        title = '健康 · ' + str(day or '日期未取得')
    else:
        bills = []
        for r in rows:
            raw=r['raw']; bill=raw.get('bill',raw.get('payload',raw)); amount=str(bill.get('money',bill.get('amount',r['normalized'].get('amount',''))))
            data = {k:bill.get(k) for k in ('type','state','currency','cateName','shopName','remark')}; data['amount']=amount
            bills.append(data); blocks.append(fields_block(r,data,key='bill:'+r['id'],field='raw.bill' if 'bill' in raw else 'raw.payload' if 'payload' in raw else 'raw'))
        values=finance_totals(bills); title='账单 · ' + str(day or '日期未取得')
    details['metrics']=values
    return content(row,typ,variant,title,blocks,details,coverage={'body':'complete','measurement':'collected_samples_only'})

"""采集与执行状态、配置及实验归档不冒充日常业务正文。"""
from pathlib import PurePosixPath

from .reading import content, fields_block, text_blocks

PROCESSOR = 'source-status-v1'
PROFILE_VERSION = 1
KINDS = ('hermes_execution_report', 'recording_processing_status', 'computer_segment_invalid', 'sync_clients',
         'collector_gaps', 'collector_meta', 'token_device', 'subscription_config',
         'recording_artifact', 'legacy_source_evidence')
STATUS_FIELDS = ('status','date','engine','checked_at','started_at','completed_at','processed','succeeded','failed','skipped','remaining',
                 'backfill_since','memory_episodes','memory_profiles','memory_writes','memory_failed','recordings','blocks','draft','attempts','retry_after')


def accepts(row):
    if row['kind'] == 'hermes_execution_report':
        return not isinstance(row['normalized'].get('content',row['raw'].get('content')),str)
    return row['kind'] in KINDS


def header(row, scope=None):
    variant = 'execution_status' if row['kind']=='hermes_execution_report' else 'configuration' if row['kind'] in ('token_device','subscription_config','collector_meta') else 'source_evidence' if row['kind']=='legacy_source_evidence' else 'archived_artifact' if row['kind'] in ('recording_artifact','source_artifact') else 'collector_status'
    return 'status',variant


def process(rows):
    if not rows: return None
    row=rows[0]; raw,n=row['raw'],row['normalized']; kind=row['kind']; typ,variant=header(row)
    document=raw.get('document',raw); blocks=[]; data={}; warnings=[]
    if kind in ('hermes_execution_report','recording_processing_status'):
        data={k:document.get(k) for k in STATUS_FIELDS if k in document}
        if kind=='recording_processing_status': data.update(summary_status=n.get('summary_status'),pending_dates=raw.get('pending_dates'))
        title='Hermes 执行状态' if kind=='hermes_execution_report' else n.get('title','Plaud 处理状态')
    elif kind=='computer_segment_invalid':
        title='电脑活动片段不完整'; data={'validation_error':n['validation_error'],'source_ref':n.get('source_ref'),'started_at':raw.get('startedAt'),'ended_at':raw.get('endedAt')}
        warnings=['source_segment_incomplete']
    elif kind=='collector_gaps':
        title='采集缺口'; data={k:raw.get(k) for k in ('started_at','ended_at','reason')}
        data.update({k:n.get(k) for k in ('measurement_scope','measurement_point','device_id','collector_id')})
    elif kind=='sync_clients':
        title='CRM 客户端同步'; data={k:raw.get(k) for k in ('source','client_id','last_seen_at','synced_through','accepted_total','duplicate_total')}
    elif kind=='token_device':
        title='Token 设备状态'; data={k:raw.get(k) for k in ('device','updated_at','received_at')}; data['timezone']=n.get('source_timezone')
        for index,provider in enumerate((raw.get('limits') or {}).get('providers',[])):
            blocks.append(fields_block(row,{k:provider.get(k) for k in ('provider','planLabel','status','updatedAt','balanceUsd','resetCredits','region')},key=f'provider:{index}',field=f'raw.limits.providers[{index}]'))
    elif kind=='subscription_config':
        title='AI 订阅配置'; data={'cost_basis':n.get('cost_basis'),'actual_paid':n.get('actual_paid')}
        for index,item in enumerate(raw['subscriptions'].get('subscriptions',[])):
            blocks.append(fields_block(row,{k:item.get(k) for k in ('provider','planName','amountMinor','currency','interval','intervalCount','startDate','endDate','autoRenew')},key=f'subscription:{index}',field=f'raw.subscriptions.subscriptions[{index}]'))
    elif kind=='collector_meta':
        title='采集器配置'; data={'key':raw.get('key'),'value':raw.get('value')}
    else:
        title=('历史来源依据 · ' if kind=='legacy_source_evidence' else '归档产物 · ') + PurePosixPath(raw.get('path','未命名')).name
        data={'path':raw.get('path'),'format':'markdown' if isinstance(n.get('content'),str) else 'structured' if isinstance(document,dict) else 'asset', 'reading_policy':'archive_with_source_fields'}
        if isinstance(n.get('content'),str): blocks=text_blocks(row,n['content'],'normalized.content')
        elif isinstance(document,dict):
            data.update({k:document[k] for k in STATUS_FIELDS + ('generated_at','schema_version','timezone','commit_count','repo_count') if k in document})
            # Known evidence text stays readable; internal samples and model wires stay archived.
            if kind=='legacy_source_evidence':
                for index,repo in enumerate(document.get('repositories',[])):
                    blocks.append(fields_block(row,{k:repo.get(k) for k in ('name','commit_count','summary')},key=f'repository:{index}',field=f'raw.document.repositories[{index}]'))
                    for position,subject in enumerate(repo.get('subjects',[])):
                        blocks.extend(text_blocks(row,subject,f'raw.document.repositories[{index}].subjects[{position}]',key=f'subject:{index}:{position}',kind='text'))
        warnings=['auxiliary_archive']
    blocks.insert(0,fields_block(row,data,field='raw.document' if 'document' in raw else 'raw'))
    return content(row,typ,variant,title,blocks,{'fields':data,'source_ref':raw.get('path'),'body_role':'auxiliary'},warnings,
        coverage={'body':'auxiliary' if blocks else 'not_applicable','business_content':False})

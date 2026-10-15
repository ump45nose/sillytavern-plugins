"""采集与执行状态、配置及实验归档不冒充日常业务正文。"""
from pathlib import PurePosixPath

from .reading import content, fields_block, text_blocks

PROCESSOR = 'source-status-v1'
PROFILE_VERSION = 1
KINDS = ('recording_processing_status', 'computer_segment_invalid', 'sync_clients',
         'collector_gaps', 'collector_meta', 'recording_artifact')
STATUS_FIELDS = ('status','date','engine','checked_at','started_at','completed_at','processed','succeeded','failed','skipped','remaining',
                 'backfill_since','recordings','blocks','draft','attempts','retry_after')


def accepts(row):
    return row['kind'] in KINDS


def header(row, scope=None):
    variant = 'configuration' if row['kind'] == 'collector_meta' else 'archived_artifact' if row['kind'] == 'recording_artifact' else 'collector_status'
    return 'status', variant


def process(rows):
    if not rows: return None
    row=rows[0]; raw,n=row['raw'],row['normalized']; kind=row['kind']; typ,variant=header(row)
    document=raw.get('document',raw); blocks=[]; data={}; warnings=[]
    if kind == 'recording_processing_status':
        data={k:document.get(k) for k in STATUS_FIELDS if k in document}
        data.update(summary_status=n.get('summary_status'),pending_dates=raw.get('pending_dates'))
        title=n.get('title','Plaud 处理状态')
    elif kind=='computer_segment_invalid':
        title='电脑活动片段不完整'; data={'validation_error':n['validation_error'],'source_ref':n.get('source_ref'),'started_at':raw.get('startedAt'),'ended_at':raw.get('endedAt')}
        warnings=['source_segment_incomplete']
    elif kind=='collector_gaps':
        title='采集缺口'; data={k:raw.get(k) for k in ('started_at','ended_at','reason')}
        data.update({k:n.get(k) for k in ('measurement_scope','measurement_point','device_id','collector_id')})
    elif kind=='sync_clients':
        title='CRM 客户端同步'; data={k:raw.get(k) for k in ('source','client_id','last_seen_at','synced_through','accepted_total','duplicate_total')}
    elif kind=='collector_meta':
        title='采集器配置'; data={'key':raw.get('key'),'value':raw.get('value')}
    else:
        title='归档产物 · ' + PurePosixPath(raw.get('path','未命名')).name
        data={'path':raw.get('path'),'format':'markdown' if isinstance(n.get('content'),str) else 'structured' if isinstance(document,dict) else 'asset', 'reading_policy':'archive_with_source_fields'}
        if isinstance(n.get('content'),str): blocks=text_blocks(row,n['content'],'normalized.content')
        elif isinstance(document,dict):
            data.update({k:document[k] for k in STATUS_FIELDS + ('generated_at','schema_version','timezone','commit_count','repo_count') if k in document})
        warnings=['auxiliary_archive']
    blocks.insert(0,fields_block(row,data,field='raw.document' if 'document' in raw else 'raw'))
    return content(row,typ,variant,title,blocks,{'fields':data,'source_ref':raw.get('path'),'body_role':'auxiliary'},warnings,
        coverage={'body':'auxiliary' if blocks else 'not_applicable','business_content':False})

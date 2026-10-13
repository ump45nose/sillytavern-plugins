"""日历、任务、Git 和 CRM 使用业务字段，而非原始 JSON。"""
from .reading import content, fields_block, text_blocks

PROCESSOR = 'business-v1'
PROFILE_VERSION = 1
KINDS = ('calendar_event', 'google_task', 'git_commit', 'people', 'facts', 'reminders', 'interactions')


def accepts(row):
    return row['kind'] in KINDS and not (row['kind'] == 'interactions' and row['raw'].get('channel') == 'wechat')


def header(row, scope=None): return 'business_object', row['kind']


def process(rows):
    if not rows: return None
    row=rows[0]; raw,n=row['raw'],row['normalized']; kind=row['kind']; blocks=[]
    if kind == 'calendar_event':
        title=n.get('title') or raw.get('summary') or '未命名日程'
        data={k:raw.get(k) for k in ('start','end','status','location','htmlLink','recurringEventId','originalStartTime')}
        data.update(calendar=n.get('calendar'), all_day=bool(raw.get('start',{}).get('date')), end_exclusive=True)
        blocks=text_blocks(row,raw.get('description',''),'raw.description',kind='text')
    elif kind == 'google_task':
        title=n.get('title') or '未命名任务'
        data={k:raw.get(k) for k in ('status','due','completed','parent','position','webViewLink','hidden','links')}
        data.update(list_id=n.get('tasklist_id'),list_title=raw.get('tasklist',{}).get('title'),history='current_snapshot_only',due_is_date_only=True)
        blocks=text_blocks(row,raw.get('notes',''),'raw.notes',kind='text')
    elif kind == 'git_commit':
        message=n.get('message') or ''; title=message.splitlines()[0] if message else 'Git 提交'
        data={k:n.get(k) for k in ('repo','sha')}; data.update(url=raw.get('html_url'),author=raw.get('commit',{}).get('author'),committer=raw.get('commit',{}).get('committer'),event_scope='commit_only')
        blocks=text_blocks(row,message,'normalized.message',kind='text')
    elif kind == 'people':
        title=raw.get('display_name') or '未命名联系人'
        data={k:raw.get(k) for k in ('id','display_name','aliases','relationship_to_me','organizations','contact_methods','tags','status','last_interaction_at')}
    elif kind == 'facts':
        title='联系人事实'; data={k:raw.get(k) for k in ('person_id','fact_type','confidence','status','source_interaction_id')}
        blocks=text_blocks(row,raw.get('content',''),'raw.content',kind='text')
    elif kind == 'reminders':
        title=raw.get('reason') or '联系提醒'; data={k:raw.get(k) for k in ('person_id','reminder_type','status','due_at','completed_at','recurrence_rule','completion_interaction_id')}
        blocks=text_blocks(row,raw.get('suggested_message',''),'raw.suggested_message',kind='text')
    else:
        title='交流记录'; data={k:raw.get(k) for k in ('person_id','channel','direction','occurred_at')}
        blocks=text_blocks(row,raw.get('summary',''),'raw.summary',kind='text')
    # Field panels are rendered from metadata; the cited block keeps them searchable.
    blocks.insert(0, fields_block(row,data))
    return content(row,'business_object',kind,title,blocks,{'fields':data,'snapshot':True})

"""CRM 业务字段的阅读方式。"""
from .reading import content, fields_block, text_blocks

PROCESSOR = 'business-v1'
PROFILE_VERSION = 1
KINDS = ('people', 'facts', 'reminders', 'interactions')


def accepts(row):
    return row['kind'] in KINDS and not (row['kind'] == 'interactions' and row['raw'].get('channel') == 'wechat')


def header(row, scope=None): return 'business_object', row['kind']


def process(rows):
    if not rows: return None
    row=rows[0]; raw,n=row['raw'],row['normalized']; kind=row['kind']; blocks=[]
    if kind == 'people':
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

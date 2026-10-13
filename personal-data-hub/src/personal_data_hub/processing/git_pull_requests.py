"""本人创建的 PR：描述、当前状态及源端时间，不猜状态转换。"""
from .reading import content, fields_block, text_blocks

PROCESSOR = 'git-pr-v1'
PROFILE_VERSION = 1
KINDS = ('git_pull_request',)


def accepts(row): return row['kind'] in KINDS

def header(row, scope=None): return 'business_object', 'git_pull_request'


def process(rows):
    if not rows: return None
    row = rows[0]; n = row['normalized']; raw = row['raw']
    values = {key:n.get(key) for key in ('repo','number','state','draft','merged','created_at','updated_at','closed_at','merged_at','url')}
    values.update(author=(raw.get('user') or {}).get('login'),
                  base_branch=(raw.get('base') or {}).get('ref'), head_branch=(raw.get('head') or {}).get('ref'),
                  history=n['history'], collection_scope=n['collection_scope'])
    blocks = [fields_block(row, values, field='normalized')]
    blocks.extend(text_blocks(row, n['body'], 'normalized.body'))
    result = content(row, 'business_object', 'git_pull_request', n['title'], blocks,
                   {'fields':values,'snapshot':True,'source_object_updated_at':n['updated_at']},
                   coverage={'body':'complete','collaboration':'authored_pull_requests_only'})

    state = '已合并' if n.get('merged') or n.get('merged_at') else '已关闭' if n['state'] == 'closed' else '草稿' if n.get('draft') else '进行中'
    result.preview = f"{n['repo']} · #{n['number']} · {state}"
    return result

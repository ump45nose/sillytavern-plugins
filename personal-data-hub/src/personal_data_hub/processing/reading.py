"""阅读加工共用的分块与来源引用。"""
from .contracts import BLOCK_CHARS, ContentBlock, ProcessedContent


def ref(row, field, **values):
    return dict(record_id=row['id'], input_hash=row['hash'], field=field, **values)


def text_blocks(row, text, field, *, key='body', kind='markdown', metadata=None, offset=0):
    return [ContentBlock(f'{key}:{start}', kind, text[start:start + BLOCK_CHARS].replace('\x00', '\uFFFD'),
                        [ref(row, field, char_start=offset + start, char_end=offset + min(len(text), start + BLOCK_CHARS))],
                        dict(metadata or {}, continuation=start > 0))
            for start in range(0, len(text), BLOCK_CHARS)]


def fields_block(row, values, *, key='fields', field='raw'):
    # Each field is cited separately; absent values stay absent rather than becoming zero.
    present = [(name, value) for name, value in values.items() if value is not None and value != '']
    return ContentBlock(key, 'fields', '\n'.join(f'{name}：{value}' for name, value in present),
                        [ref(row, field, value_key=name, transformation='field_projection') for name, _ in present], dict(values))


def content(row, typ, variant, title, blocks, metadata=None, warnings=None, coverage=None):
    details = dict(record_kind=row['kind'], record_id=row['id'], assets=row['assets'], origin='source') | (metadata or {})
    return ProcessedContent(typ, variant, str(title)[:160], next((b.text[:500] for b in blocks if b.text), ''),
                            blocks, details, warnings=warnings or [], coverage=coverage or {'body': 'complete'})

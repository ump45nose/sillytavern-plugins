"""单封邮件阅读。未取得可靠线程身份前，不按标题拼接线程。"""
import re
from html.parser import HTMLParser

from .reading import content, text_blocks

PROCESSOR = 'email-v1'
PROFILE_VERSION = 1
KINDS = ('email',)


def accepts(row): return row['kind'] in KINDS

def header(row, scope=None): return 'conversation', 'email'


class HtmlText(HTMLParser):
    """只输出文本，不传递标签、脚本、图片或外部资源。"""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'head', 'template'): self.hidden.append(tag)
        elif not self.hidden and tag in ('br', 'p', 'div', 'li', 'tr', 'blockquote', 'h1', 'h2', 'h3'): self.parts.append('\n')

    def handle_endtag(self, tag):
        if self.hidden:
            if tag == self.hidden[-1]: self.hidden.pop()
        elif tag in ('p', 'div', 'li', 'tr', 'blockquote'): self.parts.append('\n')

    def handle_data(self, data):
        if not self.hidden: self.parts.append(data)


def process(rows):
    if not rows: return None
    row = rows[0]; raw, normal = row['raw'], row['normalized']
    message = raw['message']; body = normal['body']
    html = bool(re.search(r'<(?:html|body|div|p|table|br)\b', body, re.I))
    if html:
        parser = HtmlText(); parser.feed(body); parser.close()
        readable = re.sub(r'\n{3,}', '\n\n', ''.join(parser.parts)).strip()
    else: readable = body
    # Quotations stay in order and searchable; only the reading UI collapses them.
    pieces = []; start = 0; position = 0; quoted = None
    for line in readable.splitlines(keepends=True):
        is_quote = bool(re.match(r'\s*>', line))
        if quoted is not None and is_quote != quoted:
            pieces.extend(text_blocks(row, readable[start:position], 'normalized.body', key=f'body:{start}', kind='text',
                offset=start, metadata={'quoted': quoted, 'offset_basis': 'converted_text' if html else 'source', 'transformation': 'html_to_text' if html else 'none'}))
            start = position
        quoted = is_quote
        position += len(line)
    pieces.extend(text_blocks(row, readable[start:], 'normalized.body', key=f'body:{start}', kind='text', offset=start,
        metadata={'quoted': bool(quoted), 'offset_basis': 'converted_text' if html else 'source', 'transformation': 'html_to_text' if html else 'none'}))
    return content(row, 'conversation', 'email', normal.get('subject') or '无主题邮件', pieces,
        {'subject': normal.get('subject'), 'sender': normal.get('sender'), 'recipients': message.get('recipients', []),
         'message_id': normal.get('message_id'), 'in_reply_to': message.get('in_reply_to'), 'references': message.get('references'),
         'account': raw.get('account'), 'threading': 'single_message', 'format': 'text', 'source_format': 'html' if html else 'text',
         'body_chars': len(readable), 'source_body_chars': len(body), 'attachments': message.get('attachments', [])},
        warnings=['html_converted_to_text'] if html else [])

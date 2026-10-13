import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { transform } from 'esbuild';
const { code } = await transform(await readFile(new URL('../src/addons/record-export/xml-export.ts', import.meta.url), 'utf8'), { loader: 'ts', format: 'esm' });
const { scanXml, parseMessage, filterContent, filterMessage, tagStatistics, exportParts } = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'));
const parsed = text => parseMessage({ id: 0, name: '角色', role: 'assistant', text });
const options = { mode: 'include', tags: ['content', 'after'], keepTags: false, roles: ['assistant', 'user'], from: 1, to: 100, keyword: '' };
test('extracts repeated blocks in source order with attributes and quoted angle brackets', () => {
  const source = parsed('outside<content scene="a>b">甲</content><after id="2">乙</after><content>丙</content>tail');
  assert.equal(filterContent(source, options), '甲\n\n乙\n\n丙');
  assert.equal(source.text.includes('outside'), true);
});
test('nested selections do not duplicate text, including equal-name nesting', () => {
  const source = parsed('<content>A<after>B</after>C<content>D</content></content>');
  assert.equal(filterContent(source, options), 'ABCD');
  assert.equal(filterContent(source, { ...options, keepTags: true }), source.text);
  assert.deepEqual(source.blocks.map(b => [b.name, b.parent, b.depth]), [['content', null, 0], ['after', 0, 1], ['content', 0, 1]]);
});
test('exclude removes complete nested think blocks and leaves all other bytes untouched', () => {
  const source = parsed('前<think x="1">秘密<think>内部</think>尾</think><content>正文</content>后');
  assert.equal(filterContent(source, { ...options, mode: 'exclude', tags: ['think'] }), '前<content>正文</content>后');
});
test('inline retain and exclude rules combine, including excluded ancestors and malformed descendants', () => {
  const source = parsed('<think><content>不要导出</content></think><content>A<think>秘密</think><after>B</after>C</content><after>D</after>');
  assert.equal(filterContent(source, { ...options, excludeTags: ['think', 'after'] }), 'AC');
  assert.equal(filterContent(source, { ...options, excludeTags: ['think'], keepTags: true }), '<content>A<after>B</after>C</content>\n\n<after>D</after>');
  assert.equal(filterContent(parsed('<content>公开<think>秘密</content>尾'), { ...options, excludeTags: ['think'] }), '公开');
  assert.equal(filterContent(source, { ...options, mode: 'all', excludeTags: ['think'] }), '<content>A<after>B</after>C</content><after>D</after>');
});
test('unclosed and mismatched excluded blocks are removed through end of message', () => {
  for (const text of ['公开<think>秘密', '公开<content><think>秘密</content>尾部', '公开<think attr="秘密', '公开<think']) {
    const source = parsed(text);
    assert.ok(source.warnings.length);
    assert.equal(filterContent(source, { ...options, mode: 'exclude', tags: ['think'] }).includes('秘密'), false);
    assert.equal(filterContent(source, { ...options, mode: 'include', tags: ['think'] }), '');
  }
});
test('comments, CDATA, processing instructions, less-than prose and escaped tags are not structural blocks', () => {
  const source = parsed('a < b &lt;think&gt; <!-- <think>x</think> --> <![CDATA[<think>x</think>]]> <?xml version="1.0"?><content>正文</content>');
  assert.deepEqual(source.blocks.map(b => b.name), ['content']);
  assert.equal(filterContent(source, options), '正文');
});
test('supports self-closing, Unicode and namespace names without HTML void tags swallowing XML', () => {
  const source = parsed('<content>A<br>B<img src="x"><ns:状态 值="好">内容</ns:状态><after/></content>');
  assert.equal(source.warnings.length, 0);
  assert.equal(filterContent(source, { ...options, tags: ['ns:状态'] }), '内容');
  assert.equal(filterContent(source, { ...options, tags: ['after'], keepTags: true }), '<after/>');
});
test('filters roles, human-visible floor range and keywords consistently, including first/user messages', () => {
  const user = parseMessage({ id: 0, name: '我', role: 'user', text: 'outside<content>你好</content><think>秘密</think>' });
  assert.equal(filterMessage(user, options).text, '你好');
  assert.equal(filterMessage(user, { ...options, roles: ['assistant'] }), null);
  assert.equal(filterMessage(user, { ...options, from: 2 }), null);
  assert.equal(filterMessage(user, { ...options, keyword: '你好' }).id, 0);
  assert.equal(filterMessage(user, { ...options, keyword: '秘密' }), null);
});
test('statistics distinguish nested paths, count blocks and distinct floors', () => {
  const data = [parsed('<content><after>A</after><after>B</after></content>'), parseMessage({ id: 1, name: '我', role: 'user', text: '<after>C</after>' })];
  const stats = tagStatistics(data);
  assert.equal(stats.find(s => s.path === 'content / after').count, 2);
  assert.equal(stats.find(s => s.path === 'content / after').floors, 1);
  assert.equal(stats.find(s => s.path === 'after').depth, 0);
});
test('empty/no-match include produces no messages; full export keeps the exact source', () => {
  const source = parsed('普通正文 {{user}} ```xml\n<content>示例</content>\n```');
  assert.equal(filterMessage(source, { ...options, tags: [] }), null);
  assert.equal(filterContent(source, { ...options, mode: 'all' }), source.text);
});
test('text/Markdown export preserves content and can omit all added metadata', () => {
  const messages = [{ id: 2, name: '角色', role: 'assistant', text: '第一行\n第二行 {{char}}' }];
  assert.equal(exportParts(messages, 'txt', false).join(''), '第一行\n第二行 {{char}}\n\n');
  assert.ok(exportParts(messages, 'md', true).join('').startsWith('## 3 层 · 角色'));
});

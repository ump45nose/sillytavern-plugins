import http from 'node:http';

const requests = [];
const server = http.createServer(async (req, res) => {
    if (req.url === '/requests') {
        if (req.method === 'DELETE') requests.length = 0;
        res.setHeader('content-type', 'application/json');
        res.end(JSON.stringify(requests));
        return;
    }
    if (req.url === '/v1/models') {
        res.setHeader('content-type', 'application/json');
        res.end(JSON.stringify({ object: 'list', data: [{ id: 'workbench-fixture', object: 'model', owned_by: 'local-fixture' }] }));
        return;
    }
    if (req.url !== '/v1/chat/completions' || req.method !== 'POST') {
        res.writeHead(404).end();
        return;
    }
    let text = '';
    for await (const chunk of req) {
        text += chunk;
        if (text.length > 1024 * 1024) { res.writeHead(413).end(); return; }
    }
    let body;
    try { body = JSON.parse(text); } catch { res.writeHead(400).end(); return; }
    requests.push({ at: new Date().toISOString(), path: req.url, body });
    if (requests.length > 100) requests.shift();
    const lastUser = body.messages?.findLast(message => message.role === 'user');
    const slow = JSON.stringify(lastUser?.content).includes('WB_SLOW');
    // The workbench's options prompt asks for a block at the end of the reply.
    const options = JSON.stringify(body.messages).includes('[剧情选项]')
        ? '\n<options><option title="追上去">踩着脚印追进林子，天黑前找到他。</option><option title="回村">先回村里报信。</option><option>原地生火等他</option></options>'
        : '';
    const reply = (slow ? '慢速验证回复。'.repeat(30) : '工作台验证回复：流式、世界书与插件链路正常。') + options;
    const base = { id: 'wb-fixture', object: 'chat.completion', created: Math.floor(Date.now() / 1000), model: 'workbench-fixture' };
    if (!body.stream) {
        res.setHeader('content-type', 'application/json');
        res.end(JSON.stringify({ ...base, choices: [{ index: 0, message: { role: 'assistant', content: reply }, finish_reason: 'stop' }] }));
        return;
    }
    res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-cache', connection: 'keep-alive' });
    let index = 0;
    const interval = setInterval(() => {
        if (index < reply.length) {
            const content = reply.slice(index, index += 4);
            res.write(`data: ${JSON.stringify({ ...base, object: 'chat.completion.chunk', choices: [{ index: 0, delta: { content }, finish_reason: null }] })}\n\n`);
        } else {
            res.end(`data: ${JSON.stringify({ ...base, object: 'chat.completion.chunk', choices: [{ index: 0, delta: {}, finish_reason: 'stop' }] })}\n\ndata: [DONE]\n\n`);
            clearInterval(interval);
        }
    }, slow ? 250 : 30);
    res.on('close', () => clearInterval(interval));
});
const port = Number(process.env.PORT) || 4010, host = process.env.HOST || '0.0.0.0';
server.listen(port, host, () => console.log(`Deterministic test provider listening on ${port}; no external model calls.`));

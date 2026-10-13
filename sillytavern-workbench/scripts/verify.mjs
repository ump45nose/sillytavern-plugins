import assert from 'node:assert/strict';
import { launch, session, ready, createCharacter, connect, urls, save, artifacts, resetSyntheticChats } from './browser.mjs';
import path from 'node:path';

resetSyntheticChats();
const browser = await launch();
const results = { checkedAt: new Date().toISOString(), model: 'deterministic local fixture', checks: [], errors: {} };
const check = (name, details) => { results.checks.push({ name, passed: true, details }); console.log('PASS', name); };

try {
    const baseline = await session(browser);
    await ready(baseline.page, urls.baseline);
    assert.equal(await baseline.page.evaluate(() => Boolean(window.workbenchProbe)), false);
    await createCharacter(baseline.page);
    await connect(baseline.page);
    const baseReply = await baseline.page.evaluate(() => SillyTavern.getContext().generateRaw({ prompt: '官方基线验证', api: 'openai' }));
    assert.match(baseReply, /工作台验证回复/);
    results.errors.baseline = baseline.errors;
    assert.deepEqual(baseline.errors, []);
    check('official baseline starts and generates through the unchanged runtime', { reply: baseReply });
    await baseline.context.close();

    const live = await session(browser);
    const page = live.page;
    await ready(page, urls.validation, { probe: true });
    await page.waitForFunction(() => typeof window.TavernHelper?.getChatMessages === 'function');
    check('extension mounts and helper API is available', await page.evaluate(() => workbenchProbe.capabilities()));

    const restoration = await page.evaluate(async () => {
        const probe = workbenchProbe;
        const input = document.getElementById('send_textarea');
        const chat = document.getElementById('chat');
        const nativeValueDescriptor = Object.getOwnPropertyDescriptor(input, 'value');
        input.value = '**中文草稿**\n<xml>保留</xml> {{char}}';
        input.setSelectionRange(2, 6);
        const events = SillyTavern.getContext().eventSource.events;
        const count = () => Object.values(events).reduce((sum, x) => sum + x.length, 0);
        const first = count();
        for (let i = 0; i < 5; i++) { probe.unmount(); await probe.mount(); }
        const last = count();
        probe.unmount();
        const result = {
            sameChat: chat === document.getElementById('chat') && chat === probe.nativeNodes.chat,
            sameInput: input === document.getElementById('send_textarea') && input === probe.nativeNodes.input,
            draft: input.value, selection: [input.selectionStart, input.selectionEnd],
            listenerCountStable: first === last,
            noPanel: !document.getElementById('wb-probe-panel'),
            inputUntouched: Object.getOwnPropertyDescriptor(input, 'value') === nativeValueDescriptor,
        };
        await probe.mount();
        return result;
    });
    assert.equal(restoration.sameChat && restoration.sameInput && restoration.listenerCountStable && restoration.noPanel && restoration.inputUntouched, true);
    assert.equal(restoration.draft, '**中文草稿**\n<xml>保留</xml> {{char}}');
    assert.deepEqual(restoration.selection, [2, 6]);
    check('native fallback preserves nodes, draft, selection and listener counts', restoration);

    await createCharacter(page);
    await connect(page);
    const wiFixture = await page.evaluate(async () => {
        // Test setup only: this version-specific import is not in the plugin.
        const wi = await import('/scripts/world-info.js');
        const name = 'WorkbenchFixtureWorld';
        const data = { entries: {} };
        const entry = wi.createWorldInfoEntry(name, data);
        Object.assign(entry, { key: ['wb_lore'], content: 'WB_LORE_CONTENT：灯塔位于北岸。',
            comment: '隔离世界书命中验证', constant: false, disable: false, selective: false });
        await SillyTavern.getContext().saveWorldInfo(name, data, true);
        await SillyTavern.getContext().updateWorldInfoList();
        wi.selected_world_info.splice(0, wi.selected_world_info.length, name);
        wi.world_info.globalSelect = wi.selected_world_info;
        return { name, uid: entry.uid };
    });
    await page.evaluate(() => workbenchProbe.clear());
    await page.locator('#send_textarea').fill('wb_lore 请介绍灯塔。');
    await page.locator('#send_but').click();
    await page.waitForFunction(() => {
        const context = SillyTavern.getContext();
        return context.chat.at(-1)?.is_user === false && context.chat.at(-1)?.mes?.includes('链路正常。') && !context.streamingProcessor;
    }, null, { timeout: 30_000 });
    const stream = await page.evaluate(() => {
        const record = workbenchProbe.records.at(-1);
        return { record, reply: SillyTavern.getContext().chat.at(-1).mes };
    });
    save('request-trace.json', stream);
    assert.equal(stream.record.status, 200);
    assert.equal(stream.record.body.stream, true);
    assert.equal(stream.record.assemblyEvent, 'CHAT_COMPLETION_SETTINGS_READY');
    assert(stream.record.body.messages.some(x => JSON.stringify(x.content).includes('WB_LORE_CONTENT')));
    assert(stream.record.worldInfo.some(x => x.content.includes('WB_LORE_CONTENT')));
    assert.equal(stream.record.worldInfoEvidence, 'WORLD_INFO_ACTIVATED');
    assert.match(stream.reply, /工作台验证回复/);
    check('native streaming generation captures assembled prompt and actual world-info activation', {
        world: wiFixture, traceId: stream.record.id, reply: stream.reply,
        capturePoint: stream.record.capturePoint, worldInfoEvidence: stream.record.worldInfoEvidence,
    });
    save('request-trace.json', stream);

    // Capture the server-to-model payload independently at the local provider.
    const providerRequests = await live.context.request.get(urls.mock + '/requests');
    assert.equal(providerRequests.status(), 200);
    const outbound = (await providerRequests.json()).at(-1);
    assert.deepEqual(outbound.body.messages, stream.record.body.messages);
    assert.equal(outbound.body.stream, true);
    check('local provider observes the final server request; payload matches captured messages', {
        serverEndpoint: outbound.path, messagesEqual: true,
        note: 'Equality verified for this custom OpenAI-compatible fixture, not asserted for every provider.',
    });
    save('provider-request.json', outbound);

    const jsonReply = await page.evaluate(() => SillyTavern.getContext().generateRaw({ prompt: '非流式验证', api: 'openai' }));
    assert.match(jsonReply, /工作台验证回复/);
    assert.equal(await page.evaluate(() => workbenchProbe.records.at(-1).body.stream), false);
    check('non-streaming generation remains intact', { reply: jsonReply });

    const beforeStop = await page.evaluate(() => workbenchProbe.records.length);
    await page.locator('#send_textarea').fill('WB_SLOW 取消验证');
    await page.locator('#send_but').click();
    await page.waitForFunction(count => workbenchProbe.records.length > count && workbenchProbe.records.at(-1).status === 200, beforeStop);
    await page.evaluate(() => SillyTavern.getContext().stopGeneration());
    await page.waitForFunction(() => !SillyTavern.getContext().streamingProcessor, null, { timeout: 10_000 });
    check('native stop interrupts streaming without waiting for the complete reply', { stopped: true });

    const helperResult = await page.evaluate(async () => {
        const helper = window.TavernHelper;
        await helper.createChatMessages([{ role: 'assistant', message: '```html\n<!DOCTYPE html><html><head></head><body><button id="wb-iframe-button" onclick="document.body.dataset.clicked=String(Number(document.body.dataset.clicked||0)+1)">验证交互</button><p>WB_IFRAME</p></body></html>\n```' }]);
        const messages = helper.getChatMessages('0-{{lastMessageId}}');
        return { count: messages.length, last: messages.at(-1).message };
    });
    assert.match(helperResult.last, /WB_IFRAME/);
    await page.waitForFunction(() => [...document.querySelectorAll('#chat iframe')].some(x => x.src || x.srcdoc), null, { timeout: 20_000 });
    let iframe;
    for (let i = 0; i < 120; i++) {
        for (const frame of page.frames().filter(frame => frame !== page.mainFrame())) {
            if (await frame.locator('#wb-iframe-button').count()) { iframe = frame; break; }
        }
        if (iframe) break;
        await new Promise(resolve => setTimeout(resolve, 250));
    }
    assert(iframe, 'Helper should create its own real iframe');
    await iframe.locator('#wb-iframe-button').click({ timeout: 30_000 });
    assert.equal(await iframe.locator('body').getAttribute('data-clicked'), '1');
    await page.evaluate(() => workbenchProbe.unmount());
    await iframe.locator('#wb-iframe-button').click();
    assert.equal(await iframe.locator('body').getAttribute('data-clicked'), '2');
    check('helper message APIs and real HTML iframe interaction survive native fallback', { messages: helperResult.count, iframe: true });
    await page.screenshot({ path: path.join(artifacts, 'native-fallback.png') });
    await page.evaluate(() => workbenchProbe.mount());
    await page.screenshot({ path: path.join(artifacts, 'desktop-probe.png') });
    results.errors.validation = live.errors;
    // CDN-related frame errors are reported separately; never suppress a main-frame startup failure.
    assert.deepEqual(live.errors, []);
    await live.context.close();

    const disabled = await session(browser, { probe: false });
    await ready(disabled.page, urls.validation);
    assert.equal(await disabled.page.evaluate(() => Boolean(window.workbenchProbe)), false);
    await disabled.page.waitForFunction(() => typeof window.TavernHelper?.getChatMessages === 'function');
    check('official extension-disable mechanism loads the native UI with helper intact', {});
    assert.deepEqual(disabled.errors, []);
    await disabled.context.close();

    const mobile = await session(browser, { mobile: true });
    await ready(mobile.page, urls.validation);
    await mobile.page.waitForFunction(()=>workbench.mounted&&document.body.classList.contains("wb-mobile"));
    const mobileState = await mobile.page.evaluate(() => ({
        width:innerWidth,mounted:workbench.mounted,sameInput:workbench.nativeNodes.input===document.getElementById('send_textarea'),secureContext:isSecureContext,
    }));
    assert.equal(mobileState.mounted,true);
    assert.equal(mobileState.sameInput,true);
    await mobile.page.screenshot({path:path.join(artifacts,'mobile-workbench.png')});
    check('narrow viewport mounts PWA while retaining native input',mobileState);
    assert.deepEqual(mobile.errors, []);
    await mobile.context.close();
    results.passed = true;
} catch (error) {
    results.passed = false;
    results.failure = error.stack;
    process.exitCode = 1;
    console.error(error);
} finally {
    save('verification.json', results);
    await browser.close();
}

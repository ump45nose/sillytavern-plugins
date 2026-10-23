#!/usr/bin/env python3
"""Apply the local-account adapter to a verified Token Monitor 0.75.0 source copy.

The baseline stays outside aggregate Git. The hashes identify the files verified
against the installed Mac app, not the older NAS agent/reference checkout.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
PINS = {
    'src/electron/main.js': '44ddd8971f9df102a43b2d357590d690a3f08c91a5e09d6820ec246429df0ee9',
    'src/electron/renderer/app.js': 'fd4045007a087792aa4e4ea6376b21f115d0a40abced76937cae88d4f1a2e0c9',
    'src/shared/providers/grok/account.js': '7c4a5f1f38ea7772786a0bb1f2ce17b32de7dab34e3335638dd50394c2c32106',
    'src/shared/providers/cursor/limits.js': 'b4978259df514470c1b08751df14d9196dbd1674fbc8c07e8ae25ec466eb55bf',
}


def replace(text, before, after):
    if text.count(before) != 1:
        raise ValueError('Pinned Token Monitor patch does not apply: ' + before[:80])
    return text.replace(before, after, 1)


def prepare(source, destination):
    if json.loads((source / 'package.json').read_text())['version'] != '0.75.0':
        raise ValueError('Token Monitor 0.75.0 required')
    for name, digest in PINS.items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != digest:
            raise ValueError('Baseline mismatch: ' + name)
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Destination must be empty')
    shutil.copytree(source, destination, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('.git', 'node_modules', 'dist', '.env', 'data', '*.log'))
    main = destination / 'src/electron/main.js'
    text = main.read_text()
    text = replace(text, 'app.whenReady().then(() => {', 'app.whenReady().then(async () => {')

    def lift(channel, name, arguments, wrapper, transform):
        nonlocal text
        start = text.index("  ipcMain.handle('" + channel + "', async (")
        body_start = text.index(' => {\n', start) + len(' => {\n')
        end = text.index('\n  });', body_start)
        body = transform(text[body_start:end])
        text = text[:start] + '  async function ' + name + '(' + arguments + ') {\n' + body + '\n  }\n' + wrapper + text[end + len('\n  });'):]

    def cursor(body):
        body = replace(body, '      const accountId = await cursorAuth.runCursorLogin(token);',
                       '      lifecycle.commit?.();\n      const accountId = await cursorAuth.runCursorLogin(token);')
        return replace(body, 'return { ok: true, email: probeResult.user.email, status: await cursorStatusValue() };',
                       "return { ok: true, accountKey: require('../shared/hashKey').hashKey('cursor', cursorAuth.canonicalCursorUserId(probeResult.user?.sub) || accountId), email: probeResult.user.email, status: await cursorStatusValue() };")

    lift('cursor:loginManual', 'localCursorLogin', 'raw, lifecycle = {}',
         "  ipcMain.handle('cursor:loginManual', (_event, raw) => localCursorLogin(raw));", cursor)

    def codex(body):
        body = replace(body, "      if (!event.sender.isDestroyed()) {\n        event.sender.send('codex:loginStatus', {\n          ...payload,\n          flowId\n        });\n      }", '      notify({ ...payload, flowId });')
        body = replace(body, 'webContentsId: event.sender.id,', 'webContentsId: owner,')
        body = replace(body, 'if (codexLoginController === controller) codexLoginCanCancel = false;',
                       'lifecycle.commit?.();\n          if (codexLoginController === controller) codexLoginCanCancel = false;')
        body = replace(body, '    let streamed = \'\';', "    const abort = () => controller.abort();\n    lifecycle.signal?.addEventListener('abort', abort, { once: true });\n    let streamed = '';")
        return replace(body, '    } finally {', "    } finally {\n      lifecycle.signal?.removeEventListener('abort', abort);")

    lift('codex:addAccount', 'localCodexLogin', 'notify, request = {}, owner = 0, lifecycle = {}',
         "  ipcMain.handle('codex:addAccount', (event, request = {}) => localCodexLogin(payload => { if (!event.sender.isDestroyed()) event.sender.send('codex:loginStatus', payload); }, request, event.sender.id));", codex)

    def copilot(body):
        body = replace(body, "      if (!event.sender.isDestroyed()) event.sender.send('copilot:loginStatus', { ...payload, flowId });", '      notify({ ...payload, flowId });')
        body = replace(body, '    copilotLoginController = controller;', "    copilotLoginController = controller;\n    const abort = () => controller.abort();\n    lifecycle.signal?.addEventListener('abort', abort, { once: true });")
        body = replace(body, "      settings.copilotApiToken =", "      lifecycle.commit?.();\n      settings.copilotApiToken =")
        return replace(body, '    } finally {', "    } finally {\n      lifecycle.signal?.removeEventListener('abort', abort);")

    lift('copilot:signIn', 'localCopilotLogin', 'notify, request = {}, lifecycle = {}',
         "  ipcMain.handle('copilot:signIn', (event, request = {}) => localCopilotLogin(payload => { if (!event.sender.isDestroyed()) event.sender.send('copilot:loginStatus', payload); }, request));", copilot)

    text = replace(text, 'async function addAntigravityManagedAccount() {', 'async function addAntigravityManagedAccount(lifecycle = {}) {')
    text = replace(text, '  antigravityOAuthLoginController = controller;', "  antigravityOAuthLoginController = controller;\n  const abort = () => controller.abort();\n  lifecycle.signal?.addEventListener('abort', abort, { once: true });")
    text = replace(text, '    if (!writeAntigravityCredential(account.id, {', '    lifecycle.commit?.();\n    if (!writeAntigravityCredential(account.id, {')
    text = replace(text, '    return { ok: true, accounts: antigravityAccountsForRenderer() };', '    return { ok: true, account, accounts: antigravityAccountsForRenderer() };')
    text = replace(text, '    if (antigravityOAuthLoginController === controller) antigravityOAuthLoginController = null;', "    lifecycle.signal?.removeEventListener('abort', abort);\n    if (antigravityOAuthLoginController === controller) antigravityOAuthLoginController = null;")

    # An externally managed empty projection is not permission to erase local
    # records or seed the old fee list into the independent ledger.
    text = replace(text, 'function cacheSharedSubscriptions(doc, hub) {', "function cacheSharedSubscriptions(doc, hub) {\n  if (doc.managedExternally === true) {\n    const changed = hubSubscriptionsHub !== hub || hubSubscriptions?.managedExternally !== true;\n    hubSubscriptions = doc; hubSubscriptionsHub = hub;\n    return changed;\n  }")
    text = replace(text, '    subscriptions: effectiveSubscriptions(),', "    subscriptionsManagedExternally: subscriptionsDocumentFor(currentHubIdentity())?.managedExternally === true,\n    subscriptions: effectiveSubscriptions(),")
    text = replace(text, '    if (seedFromLocal && !doc.updatedAt && local.length > 0) {', '    if (!doc.managedExternally && seedFromLocal && !doc.updatedAt && local.length > 0) {')
    text = replace(text, '    const orphansChanged = seedFromLocal && local.length > 0\n      ? rememberOrphanedSubscriptions(local, doc)', '    const orphansChanged = !doc.managedExternally && seedFromLocal && local.length > 0\n      ? rememberOrphanedSubscriptions(local, doc)')
    text = replace(text, '  scheduleStartupAppUpdateCheck();', (HERE / 'electron-local-control.js.inc').read_text() + '\n  scheduleStartupAppUpdateCheck();')
    main.write_text(text)
    shutil.copy2(HERE / 'local-control.js', destination / 'src/electron/local-account-control.js')

    credentials = destination / 'src/electron/limits/credentialCommands.js'
    text = credentials.read_text()
    text = replace(text, 'async function saveCredential(providerId, values) {', 'async function saveCredential(providerId, values, lifecycle = {}) {')
    text = replace(text, '    const settings = applySettingsPatch({\n      ...candidate,', '    lifecycle.commit?.();\n    const settings = applySettingsPatch({\n      ...candidate,')
    credentials.write_text(text)
    grok = destination / 'src/shared/providers/grok/account.js'
    grok.write_text(replace(grok.read_text(), '  fields: [],', "  fields: [{ key: 'grokBearerToken', kind: 'credential', storePath: ['providers', 'grok', 'bearerToken'], project: 'set' }],"))
    renderer = destination / 'src/electron/renderer/app.js'
    text = renderer.read_text()
    text = replace(text, 'function renderSubscriptionSettings() {', "function renderSubscriptionSettings() {\n  const external = state.settings?.subscriptionsManagedExternally === true;\n  document.querySelector('[data-settings-section=\"subscriptions\"]')?.parentElement?.classList.toggle('hidden', external);\n  if (external) return;")
    for signature in ('function beginSubscriptionAdd() {', 'function beginSubscriptionEdit(id) {', 'async function submitSubscription() {'):
        text = replace(text, signature, signature + '\n  if (state.settings?.subscriptionsManagedExternally) return;')
    renderer.write_text(text)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    options = parser.parse_args()
    print(prepare(options.source.resolve(), options.destination.resolve()))

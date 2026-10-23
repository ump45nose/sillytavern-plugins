  // Local bridge and native UI share the controllers below; only presentation
  // and transport differ. Supplier credentials never leave this process.
  const { startLocalAccountControl, safeAccount } = require('./local-account-control');
  const localAccounts = () => (localArchiveSourceDevice()?.limits?.providers || []).filter(p => p.accountKey);
  const accountFailure = code => Object.assign(new Error(code), { code });
  const localAccountControl = process.platform === 'darwin' ? await startLocalAccountControl({
    dataDir: app.getPath('userData'),
    accounts: localAccounts,
    select(id, workspaceId) {
      const pending = codexWorkspaceSelection;
      if (!pending || pending.flowId !== id || pending.webContentsId !== 'local-control'
        || !pending.workspaceIds.has(workspaceId)) return false;
      pending.finish(workspaceId); return true;
    },
    cancel(provider, id) {
      if (provider === 'codex' && codexLoginFlowId === id && codexLoginCanCancel) codexLoginController?.abort();
      if (provider === 'copilot' && copilotLoginFlowId === id) copilotLoginController?.abort();
      if (provider === 'antigravity') cancelAntigravityManagedAccountLogin();
    },
    async connect(input, context) {
      if (!deviceRuntimeHandle || isExternalAgentActive()) throw accountFailure('runtime_unavailable');
      if (input.provider === 'claude' && settings.claudeDesktopLocalOnly !== true) throw accountFailure('local_mode_required');
      let wanted = input.account || '';
      if (input.method !== 'discover') {
        let result;
        if (input.provider === 'cursor') {
          result = await localCursorLogin(input.credential, context);
          wanted = result.accountKey || '';
        } else if (input.provider === 'codex') {
          result = await localCodexLogin(context.emit, { flowId: context.id }, 'local-control', context);
          wanted = result.account?.accountKey || '';
        } else if (input.provider === 'antigravity') {
          result = await addAntigravityManagedAccount(context);
          wanted = result.account?.accountKey || '';
        } else if (input.provider === 'copilot') {
          result = await localCopilotLogin(context.emit, { flowId: context.id }, context);
        } else if (input.provider === 'zai') {
          const key = normalizeAccountField('zaiApiKey', input.credential);
          result = await credentialCommands.saveCredential('zai', { zaiApiKey: key, zaiApiRegion: input.region || 'global' }, context);
          result.ok = result.saved;
          wanted = require('../shared/hashKey').hashKey('zai', key);
        } else if (input.provider === 'grok') {
          const token = String(input.credential || '').trim();
          const candidate = await require('../shared/providers/grok/limits').fetchGrokLimits(
            { grokBearerToken: token }, { ...credentialProbeDeps(), signal: context.signal });
          if (candidate.status === 'unauthorized' || !candidate.accountKey) throw accountFailure('invalid_credential');
          context.commit();
          applySettingsPatch({ grokBearerToken: token, limitsEnabled: true,
            limitProviders: [...new Set([...parseLimitProviders(settings.limitProviders), 'grok'])].join(',') });
          result = { ok: true }; wanted = candidate.accountKey;
        }
        if (!result?.ok) throw accountFailure('invalid_credential');
      } else {
        const options = localAccounts().filter(a => a.provider === input.provider && (!wanted || a.accountKey === wanted));
        if (options.length > 1 && !wanted) throw accountFailure('account_unavailable');
        if (options.length === 1) wanted = options[0].accountKey;
      }
      // Explicitly adding a provider enables that provider only. Claude's local
      // mode is checked above, never changed to obtain a new reading.
      if (!context.signal.aborted) {
        if (!parseLimitProviders(settings.limitProviders).includes(input.provider)) {
          context.commit();
          applySettingsPatch({ limitsEnabled: true, limitProviders: [...parseLimitProviders(settings.limitProviders), input.provider].join(',') });
        }
      } else throw accountFailure('cancelled');
      let synced = false;
      try {
        await queueLimitInvalidation({ provider: input.provider, ...(wanted ? { accountKey: wanted } : {}) }, 'hub-connect', { clear: false });
        // Flush uses the existing ordered upload sink; it never posts a second,
        // synthetic device record or assigns a new observation timestamp.
        await Promise.race([
          deviceRuntimeHandle.flush().then(() => { synced = settings.hubMode === 'client'; }),
          new Promise(resolve => { const timer = setTimeout(resolve, 15000); timer.unref(); })
        ]);
      } catch (_) { /* linked accounts remain useful while NAS is offline */ }
      const matches = localAccounts().filter(a => a.provider === input.provider && (wanted ? a.accountKey === wanted
        : input.method === 'discover' || Date.parse(a.updatedAt) >= context.startedAt));
      let account = matches.length === 1 ? safeAccount(matches[0]) : null;
      if (!account && wanted) account = safeAccount({ provider: input.provider, accountKey: wanted, status: 'unavailable' });
      if (!account) throw accountFailure('account_unavailable');
      context.commit();
      return { account, syncStatus: synced ? 'synced' : 'pending' };
    }
  }).catch(() => { console.warn('[local-account-control] unavailable'); return null; }) : null;
  app.prependOnceListener('before-quit', () => { void localAccountControl?.close(); });

import test from 'node:test';
import assert from 'node:assert/strict';
import { extractVersion, versionProblem } from '../perf-extension/lib/version.js';
import { GZIP_MIN_BYTES, isLoopbackHost, shouldGzip } from '../perf-extension/lib/gzip.js';

test('version guard accepts only the verified 1.19.x line', () => {
    assert.equal(extractVersion("SillyTavern 1.19.0 'release' (abc123)"), '1.19.0');
    assert.equal(versionProblem("SillyTavern 1.19.0 'release' (abc123)"), null);
    assert.equal(versionProblem('SillyTavern 1.19.4'), null);
    assert.match(versionProblem('SillyTavern 1.18.2'), /不在已验证范围/);
    assert.match(versionProblem('SillyTavern 1.20.0'), /不在已验证范围/);
    // displayVersion is just "SillyTavern" until getClientVersion() resolves.
    assert.match(versionProblem('SillyTavern'), /无法识别/);
});

const request = patch => ({
    pathname: '/api/settings/save',
    hostname: '192.168.31.201',
    method: 'POST',
    contentEncoding: null,
    bodyBytes: GZIP_MIN_BYTES,
    ...patch,
});

test('gzip applies to large JSON saves on the LAN, including the production host', () => {
    assert.equal(shouldGzip(request()), true);
    assert.equal(shouldGzip(request({ pathname: '/api/chats/save', hostname: 'tavern.example.com' })), true);
});

test('gzip skips small bodies, other endpoints, reads, loopback and already-encoded requests', () => {
    assert.equal(shouldGzip(request({ bodyBytes: GZIP_MIN_BYTES - 1 })), false);
    assert.equal(shouldGzip(request({ pathname: '/api/settings/get' })), false);
    assert.equal(shouldGzip(request({ pathname: '/api/characters/edit-avatar' })), false);
    assert.equal(shouldGzip(request({ method: 'GET' })), false);
    assert.equal(shouldGzip(request({ hostname: '127.0.0.1' })), false);
    // ST-BaiBai-Tools compresses chat saves itself; a second pass must not happen.
    assert.equal(shouldGzip(request({ pathname: '/api/chats/save', contentEncoding: 'gzip' })), false);
});

test('loopback detection', () => {
    for (const host of ['localhost', 'app.localhost', '127.0.0.1', '127.1.2.3', '::1', '[::1]']) assert.equal(isLoopbackHost(host), true, host);
    for (const host of ['192.168.31.201', '10.0.0.2', 'example.com']) assert.equal(isLoopbackHost(host), false, host);
});

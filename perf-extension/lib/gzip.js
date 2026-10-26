// Pure eligibility rules for the gzip save hook; the unit tests import them.

/** Large JSON save endpoints. Multipart uploads (avatars, imports) are never compressed. */
export const GZIP_PATHS = Object.freeze([
    '/api/settings/save',
    '/api/chats/save',
    '/api/chats/group/save',
    '/api/worldinfo/edit',
    '/api/presets/save',
    '/api/characters/merge-attributes',
]);

/** Below this the compression round trip costs more than the bytes it saves. */
export const GZIP_MIN_BYTES = 64 * 1024;

/** Loopback only: the server sits on the same machine, so bytes on the wire are free. */
export function isLoopbackHost(hostname) {
    const host = String(hostname ?? '').toLowerCase().replace(/^\[|\]$/g, '');
    return host === 'localhost' || host.endsWith('.localhost') || host === '::1' || /^127\./.test(host);
}

/**
 * Whether a request should go out gzip-compressed.
 * @param {{ pathname: string, hostname: string, method: string, contentEncoding: string|null, bodyBytes: number }} request
 */
export function shouldGzip({ pathname, hostname, method, contentEncoding, bodyBytes }) {
    if (!GZIP_PATHS.includes(pathname)) return false;
    if (!['POST', 'PUT', 'PATCH'].includes(String(method).toUpperCase())) return false;
    // Already compressed by another hook (ST-BaiBai-Tools compresses chat saves the same way).
    if (contentEncoding) return false;
    if (isLoopbackHost(hostname)) return false;
    return bodyBytes >= GZIP_MIN_BYTES;
}

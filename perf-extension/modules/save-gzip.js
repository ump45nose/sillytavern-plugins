/**
 * 保存请求 gzip 上行
 * 来源：ST-BaiBai-Tools src/features/gzipHook.js installSaveRequestGzipFetchHook — https://github.com/baibai-git/ST-BaiBai-Tools （作者 柏柏）
 *
 * 大的 JSON 保存请求（设置 5 MB 级、聊天、世界书、预设）用 CompressionStream 压缩后带
 * Content-Encoding: gzip 上行；1.19.0 服务端 bodyParser.json（src/server-main.js）默认 inflate:true 会解压。
 * 压缩失败、请求失败或非 2xx 时自动按未压缩原样重发一次。已带 Content-Encoding 的请求（BaiBai 压过的聊天保存）
 * 原样放行，两者同开不会重复压缩。与 BaiBai 不同，局域网地址也压缩（生产在 192.168.x），只跳过回环地址。
 */
import { addFetchHandler, requestUrl } from '../core.js';
import { shouldGzip } from '../lib/gzip.js';

async function gzip(text) {
    const stream = new Blob([text]).stream().pipeThrough(new CompressionStream('gzip'));
    return new Response(stream).blob();
}

export default {
    id: 'saveGzip',
    title: '保存请求：大于 64 KB 的 JSON 保存 gzip 压缩上行',
    async probe() {
        return typeof CompressionStream === 'function' ? null : '浏览器不支持 CompressionStream';
    },
    install() {
        return addFetchHandler(async (input, init, next) => {
            // Only plain string bodies in an init object: Request bodies, FormData and streams pass untouched.
            if (typeof input !== 'string' && !(input instanceof URL)) return next(input, init);
            const body = init?.body, url = requestUrl(input);
            if (typeof body !== 'string' || !url) return next(input, init);
            const headers = new Headers(init.headers);
            const eligible = shouldGzip({
                pathname: url.pathname,
                hostname: url.hostname,
                method: init.method ?? 'GET',
                contentEncoding: headers.get('Content-Encoding'),
                // UTF-16 length is a lower bound on UTF-8 bytes, which is all the threshold needs.
                bodyBytes: body.length,
            });
            if (!eligible) return next(input, init);
            let compressed;
            try {
                compressed = await gzip(body);
            } catch (error) {
                console.warn('[wb-perf] gzip failed, sending uncompressed', error);
                return next(input, init);
            }
            headers.set('Content-Encoding', 'gzip');
            headers.delete('Content-Length');
            try {
                const response = await next(input, { ...init, headers, body: compressed });
                if (response.ok) return response;
                console.warn(`[wb-perf] gzip ${url.pathname} returned ${response.status}, retrying uncompressed`);
            } catch (error) {
                if (init.signal?.aborted) throw error;
                console.warn(`[wb-perf] gzip ${url.pathname} failed, retrying uncompressed`, error);
            }
            return next(input, init);
        });
    },
};

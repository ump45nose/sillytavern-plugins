(function (win) {
    'use strict';
 
    function h32(str) {
        var h = 0x811c9dc5;
        for (var i = 0; i < str.length; i++) {
            h ^= str.charCodeAt(i);
            h = Math.imul(h, 0x01000193) >>> 0;
        }
        return h.toString(16).padStart(8, '0');
    }

    function fp32(raw) {
        var a = h32(raw);
        var b = h32(a + raw.slice(0, raw.length >> 1));
        var c = h32(b + raw.slice(raw.length >> 1));
        var d = h32(c + String(raw.length));
        return a + b + c + d;
    }

    function canvas() {
        try {
            var cv = document.createElement('canvas');
            cv.width = 220; cv.height = 30;
            var ctx = cv.getContext('2d');
            if (!ctx) return 'nc';
            ctx.textBaseline = 'alphabetic';
            ctx.fillStyle = '#f0a';
            ctx.fillRect(0, 0, 220, 30);
            ctx.fillStyle = '#069';
            ctx.font = '14px Arial,sans-serif';
            ctx.fillText('Lw\u8001\u738b_fp\uD83D\uDE00', 4, 20);
            ctx.fillStyle = 'rgba(100,200,50,0.8)';
            ctx.font = '11px Georgia';
            ctx.fillText('fingerprint', 80, 26);
            return cv.toDataURL().slice(-40);
        } catch (e) { return 'ce'; }
    }

    function webgl() {
        try {
            var cv = document.createElement('canvas');
            var gl = cv.getContext('webgl') || cv.getContext('experimental-webgl');
            if (!gl) return '';
            var ext = gl.getExtension('WEBGL_debug_renderer_info');
            if (ext) return gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) || '';
            return gl.getParameter(gl.RENDERER) || '';
        } catch (e) { return ''; }
    }

    function collect() {
        var n = navigator, s = screen;
        return [
            n.userAgent || '',
            (n.languages || [n.language || n.userLanguage || '']).join(','),
            s.width + 'x' + s.height + 'x' + (s.colorDepth || ''),
            (new Date()).getTimezoneOffset(),
            n.hardwareConcurrency || '',
            n.deviceMemory || '',
            n.platform || '',
            canvas(),
            webgl()
        ].join('||');
    }

    function compute() {
        return fp32(collect());
    }

    function fillPostField() {
        var el = document.getElementById('browser_fp');
        if (el && el.value === 'no_js') {
            el.value = compute();
        }
    }

    win.dzFP = { compute: compute, fillPostField: fillPostField };

    function ready(fn) {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', fn);
        } else {
            fn();
        }
    }

    ready(function () {
        if (document.getElementById('browser_fp')) {
            fillPostField();
        } else {
            var captchaEl = document.getElementById('clicaptcha-submit-info');
            if (captchaEl) {
                var inp = document.createElement('input');
                inp.type  = 'hidden';
                inp.name  = 'fingerprint';
                inp.id    = 'browser_fp';
                inp.value = 'no_js';
                captchaEl.parentNode.insertBefore(inp, captchaEl.nextSibling);
                fillPostField();
            }
        }
    });

}(window));

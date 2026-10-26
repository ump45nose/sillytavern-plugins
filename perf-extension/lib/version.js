// Pure helpers; no browser globals, so the unit tests can import them.

/** SillyTavern versions the hook points were verified against: [min, max). */
export const TESTED_RANGE = Object.freeze(['1.19.0', '1.20.0']);

/** "SillyTavern 1.19.0 'release' (abc123)" → "1.19.0"; null when absent. */
export function extractVersion(display) {
    const match = String(display ?? '').match(/(\d+)\.(\d+)\.(\d+)/);
    return match ? match.slice(1, 4).join('.') : null;
}

export function compareVersions(a, b) {
    const pa = a.split('.').map(Number), pb = b.split('.').map(Number);
    for (let i = 0; i < 3; i++) if (pa[i] !== pb[i]) return pa[i] > pb[i] ? 1 : -1;
    return 0;
}

/** Null when the version is inside the tested range, otherwise the reason the modules stay off. */
export function versionProblem(display, [min, max] = TESTED_RANGE) {
    const version = extractVersion(display);
    if (!version) return `无法识别酒馆版本（${display || '空'}）`;
    if (compareVersions(version, min) < 0 || compareVersions(version, max) >= 0)
        return `酒馆 ${version} 不在已验证范围 ${min} – <${max}`;
    return null;
}

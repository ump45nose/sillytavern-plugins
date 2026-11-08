// Check the latest upstream release and open at most one matching issue.
// --dry-run prints the decision; --latest-tag is a dry-run-only test override.
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';

const args = process.argv.slice(2);
const dryRun = args.includes('--dry-run');
const tagIndex = args.indexOf('--latest-tag');
if (args.some((arg, i) => !['--dry-run', '--latest-tag'].includes(arg) && !(tagIndex !== -1 && i === tagIndex + 1)) ||
    (tagIndex !== -1 && (!dryRun || !args[tagIndex + 1] || args[tagIndex + 1].startsWith('--')))) {
  throw new Error('Usage: node scripts/upstream-release.mjs [--dry-run] [--latest-tag <version>]');
}
const gh = (...params) => execFileSync('gh', params, { encoding: 'utf8' });
const lock = JSON.parse(readFileSync(new URL('../baseline.lock.json', import.meta.url), 'utf8'));
const repo = process.env.GITHUB_REPOSITORY || 'ump45nose/sillytavern-plugins';
const latest = tagIndex === -1
  ? JSON.parse(gh('api', 'repos/SillyTavern/SillyTavern/releases/latest'))
  : { tag_name: args[tagIndex + 1], html_url: `https://github.com/SillyTavern/SillyTavern/releases/tag/${encodeURIComponent(args[tagIndex + 1])}` };

function version(tag) {
  const match = /^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$/.exec(tag);
  if (!match) throw new Error(`Unsupported release version: ${tag}`);
  return { numbers: match.slice(1, 4).map(Number), pre: match[4]?.split('.') };
}
function compare(a, b) {
  const x = version(a), y = version(b);
  for (let i = 0; i < 3; i++) if (x.numbers[i] !== y.numbers[i]) return x.numbers[i] - y.numbers[i];
  if (!x.pre || !y.pre) return Number(!x.pre) - Number(!y.pre);
  for (let i = 0; i < Math.max(x.pre.length, y.pre.length); i++) {
    if (x.pre[i] === undefined) return -1;
    if (y.pre[i] === undefined) return 1;
    if (x.pre[i] === y.pre[i]) continue;
    const xn = /^\d+$/.test(x.pre[i]), yn = /^\d+$/.test(y.pre[i]);
    if (xn && yn) return Number(x.pre[i]) - Number(y.pre[i]);
    if (xn !== yn) return xn ? -1 : 1;
    return x.pre[i] < y.pre[i] ? -1 : 1;
  }
  return 0;
}

console.log(`基线: ${lock.upstream.release}；上游最新: ${latest.tag_name}`);
if (compare(latest.tag_name, lock.upstream.release) <= 0) {
  console.log('没有更新，无需创建 issue。');
} else {
  const title = `上游发布 ${latest.tag_name}`;
  const pages = JSON.parse(gh('api', '--paginate', '--slurp', `repos/${repo}/issues?state=open&per_page=100`));
  if (pages.flat().some(issue => !issue.pull_request && issue.title === title)) {
    console.log(`已存在打开的 issue：${title}`);
  } else {
    const body = `上游 release：[${latest.tag_name}](${latest.html_url})\n\n升级步骤详见 [docs/upstream-sync.md](https://github.com/${repo}/blob/main/docs/upstream-sync.md)。\n\n- [ ] 更新 lock 的 release、commit、镜像 digest 和 id\n- [ ] 重新准备上游源码与隔离环境\n- [ ] 运行 check、单测和相关运行时验证\n- [ ] 对照钩子点表检查兼容性\n- [ ] 部署并将生产 compose 镜像固定到新 digest`;
    if (dryRun) console.log(`只打印：将创建 issue：${title}\n\n${body}`);
    else console.log(gh('issue', 'create', '--repo', repo, '--title', title, '--body', body).trim());
  }
}

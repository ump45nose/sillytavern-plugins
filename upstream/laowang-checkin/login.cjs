const path = require('path');
const fs = require('fs');
const readline = require('readline/promises');
const { firefox } = require('playwright-firefox');

(async () => {
  if (!process.stdin.isTTY) throw new Error('Initial login needs an interactive terminal');
  const dataDir = path.resolve(process.env.LAOWANG_DATA_DIR || './data');
  const profile = path.join(dataDir, 'browser');
  fs.mkdirSync(dataDir, { recursive: true, mode: 0o700 });
  const proxy = process.env.LAOWANG_PROXY;
  const browser = await firefox.launchPersistentContext(profile, {
    headless: false,
    ...(proxy ? { proxy: { server: proxy } } : {}),
  });
  try {
    const page = browser.pages()[0] || await browser.newPage();
    await page.goto('https://laowang.vip/forum.php');
    const input = readline.createInterface({ input: process.stdin, output: process.stdout });
    await input.question('Complete login in the browser, then press Enter here.');
    input.close();
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error.message); process.exitCode = 1; });

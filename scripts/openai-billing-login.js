import puppeteer from 'puppeteer';
import {
  BalanceReadError,
  OPENAI_HOME_URL,
  findGoogleChromeExecutable,
  readBalanceFromPage,
  resolveBillingProfileDir
} from '../integrations/node/openai-balance-browser.module.js';

let browser = null;
try {
  const executablePath = findGoogleChromeExecutable();
  browser = await puppeteer.launch({
    executablePath,
    headless: false,
    userDataDir: resolveBillingProfileDir(),
    args: ['--no-first-run', '--no-default-browser-check']
  });
  const existingPages = await browser.pages();
  const page = existingPages[0] || await browser.newPage();
  await page.goto(OPENAI_HOME_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });

  const deadline = Date.now() + 15 * 60 * 1000;
  let validated = false;
  while (browser.connected && !page.isClosed() && Date.now() < deadline) {
    try {
      await readBalanceFromPage(page);
      validated = true;
      break;
    } catch {}
    await new Promise(resolve => setTimeout(resolve, 1500));
  }

  if (!validated) {
    throw new BalanceReadError(browser.connected ? 'BILLING_AUTH_REQUIRED' : 'BILLING_PAGE_UNAVAILABLE');
  }
  console.log('OPENAI_BILLING_SESSION_OK');
} catch (error) {
  const safeCodes = new Set(['BILLING_AUTH_REQUIRED', 'BILLING_PAGE_UNAVAILABLE', 'BALANCE_NOT_FOUND', 'BALANCE_AMBIGUOUS', 'GOOGLE_CHROME_NOT_FOUND']);
  console.error(safeCodes.has(error?.code) ? error.code : 'BILLING_PAGE_UNAVAILABLE');
  process.exitCode = 1;
} finally {
  if (browser?.connected) await browser.close().catch(() => {});
}

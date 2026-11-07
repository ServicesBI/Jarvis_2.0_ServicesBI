import fs from 'fs';
import path from 'path';
import puppeteer from 'puppeteer';

export const OPENAI_HOME_URL = 'https://platform.openai.com/home';
export const DEFAULT_BALANCE_REFRESH_MS = 300000;

const BALANCE_LABELS = [
  'credit balance',
  'api credit balance',
  'saldo de credito da api',
  'saldo de credito'
];

export class BalanceReadError extends Error {
  constructor(code) {
    super(code);
    this.name = 'BalanceReadError';
    this.code = code;
  }
}

function normalizeText(value) {
  return String(value || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
}

export function parseUsdValue(text) {
  const source = String(text || '');
  const matches = [...source.matchAll(/(-?)\s*(?:US\s*)?\$\s*(-?)\s*(\d[\d.,]*)/gi)];
  if (matches.length !== 1 || matches[0][1] === '-' || matches[0][2] === '-') return null;

  let numeric = matches[0][3];
  const lastDot = numeric.lastIndexOf('.');
  const lastComma = numeric.lastIndexOf(',');
  let decimalSeparator = null;

  if (lastDot >= 0 && lastComma >= 0) {
    decimalSeparator = lastDot > lastComma ? '.' : ',';
  } else if (lastDot >= 0 || lastComma >= 0) {
    const separator = lastDot >= 0 ? '.' : ',';
    const occurrences = numeric.split(separator).length - 1;
    const digitsAfter = numeric.length - numeric.lastIndexOf(separator) - 1;
    if (digitsAfter > 0 && digitsAfter <= 2) decimalSeparator = separator;
    else if (occurrences > 1 && digitsAfter === 2) decimalSeparator = separator;
  }

  if (decimalSeparator) {
    const thousandsSeparator = decimalSeparator === '.' ? ',' : '.';
    numeric = numeric.split(thousandsSeparator).join('');
    const decimalIndex = numeric.lastIndexOf(decimalSeparator);
    numeric = numeric.slice(0, decimalIndex).replace(/[.,]/g, '') + '.' + numeric.slice(decimalIndex + 1);
  } else {
    numeric = numeric.replace(/[.,]/g, '');
  }

  const value = Number(numeric);
  return Number.isFinite(value) && value >= 0 ? value : null;
}

export function parseCreditBalanceEntries(entries) {
  if (!Array.isArray(entries)) throw new BalanceReadError('BALANCE_NOT_FOUND');

  const candidates = [];
  for (const entry of entries) {
    if (!BALANCE_LABELS.includes(normalizeText(entry?.label))) continue;
    const value = parseUsdValue(entry?.valueText);
    if (value !== null) candidates.push(value);
  }

  if (candidates.length === 0) throw new BalanceReadError('BALANCE_NOT_FOUND');
  if (candidates.length !== 1) throw new BalanceReadError('BALANCE_AMBIGUOUS');
  return candidates[0];
}

export function resolveBillingProfileDir() {
  const localAppData = process.env.LOCALAPPDATA;
  if (!localAppData) throw new BalanceReadError('BILLING_SESSION_NOT_CONFIGURED');
  return path.join(localAppData, 'ServicesBI_Jarvis', 'openai-billing-profile');
}

export function findGoogleChromeExecutable() {
  if (process.platform !== 'win32') throw new BalanceReadError('GOOGLE_CHROME_NOT_FOUND');
  const candidates = [
    process.env.PROGRAMFILES && path.join(process.env.PROGRAMFILES, 'Google', 'Chrome', 'Application', 'chrome.exe'),
    process.env['PROGRAMFILES(X86)'] && path.join(process.env['PROGRAMFILES(X86)'], 'Google', 'Chrome', 'Application', 'chrome.exe'),
    process.env.LOCALAPPDATA && path.join(process.env.LOCALAPPDATA, 'Google', 'Chrome', 'Application', 'chrome.exe')
  ].filter(Boolean);

  for (const candidate of candidates) {
    const resolved = path.resolve(candidate);
    const normalized = resolved.replace(/\//g, '\\');
    const isGoogleChrome = /\\Google\\Chrome\\Application\\chrome\.exe$/i.test(normalized) &&
      path.basename(resolved).toLowerCase() === 'chrome.exe';
    if (isGoogleChrome && fs.existsSync(resolved)) return resolved;
  }
  throw new BalanceReadError('GOOGLE_CHROME_NOT_FOUND');
}

export async function readBalanceFromPage(page) {
  const entries = await page.evaluate((acceptedLabels) => {
    const normalize = value => String(value || '')
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .replace(/\s+/g, ' ')
      .trim()
      .toLowerCase();
    const hasMoney = value => /(?:US\s*)?\$\s*-?\s*\d/i.test(String(value || ''));
    const results = [];

    for (const element of document.querySelectorAll('body *')) {
      const directText = [...element.childNodes]
        .filter(node => node.nodeType === Node.TEXT_NODE)
        .map(node => node.textContent)
        .join(' ');
      const label = normalize(directText || element.getAttribute('aria-label'));
      if (!acceptedLabels.includes(label)) continue;

      const scopes = [element.nextElementSibling, element.parentElement, element.parentElement?.parentElement];
      const scope = scopes.find(candidate => candidate && hasMoney(candidate.innerText));
      if (scope) results.push({ label, valueText: scope.innerText });
    }
    return results;
  }, BALANCE_LABELS);

  return parseCreditBalanceEntries(entries);
}

function classifyPageUrl(url) {
  try {
    const parsed = new URL(url);
    if (parsed.origin !== 'https://platform.openai.com') return 'BILLING_AUTH_REQUIRED';
    if (/login|auth|signin/i.test(parsed.pathname)) return 'BILLING_AUTH_REQUIRED';
    if (parsed.pathname !== '/home') return 'BILLING_AUTH_REQUIRED';
    return null;
  } catch {
    return 'BILLING_PAGE_UNAVAILABLE';
  }
}

async function pageRequiresAuthentication(page) {
  return page.evaluate(() => {
    const text = String(document.body?.innerText || '').replace(/\s+/g, ' ').toLowerCase();
    return /\b(sign in|log in|entrar|fazer login)\b/.test(text) &&
      !/\b(credit balance|api credit balance|saldo de cr[eé]dito)\b/i.test(text);
  });
}

async function waitForConfirmedBalance(page, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  do {
    try {
      return await readBalanceFromPage(page);
    } catch (error) {
      if (error?.code === 'BALANCE_AMBIGUOUS') throw error;
    }
    await new Promise(resolve => setTimeout(resolve, 1000));
  } while (Date.now() < deadline);
  throw new BalanceReadError('BALANCE_NOT_FOUND');
}

export class OpenAIBalanceBrowser {
  constructor({ refreshMs = DEFAULT_BALANCE_REFRESH_MS, headless = true } = {}) {
    this.refreshMs = Number.isSafeInteger(refreshMs) && refreshMs > 0 ? refreshMs : DEFAULT_BALANCE_REFRESH_MS;
    this.headless = headless;
    this.browser = null;
    this.page = null;
    this.timer = null;
    this.inFlight = null;
    this.lastConfirmed = null;
    this.state = this.errorState('BILLING_SESSION_NOT_CONFIGURED');
  }

  errorState(code) {
    return {
      ok: false,
      currency: 'USD',
      balance: null,
      source: 'openai_platform_home',
      updatedAt: null,
      refreshMs: this.refreshMs,
      stale: false,
      authRequired: code === 'BILLING_AUTH_REQUIRED' || code === 'BILLING_SESSION_NOT_CONFIGURED',
      code
    };
  }

  getState() {
    return { ...this.state };
  }

  start() {
    if (this.timer) return;
    void this.refresh();
    this.timer = setInterval(() => void this.refresh(), this.refreshMs);
  }

  async ensurePage() {
    const profileDir = resolveBillingProfileDir();
    if (!fs.existsSync(profileDir)) throw new BalanceReadError('BILLING_SESSION_NOT_CONFIGURED');
    const executablePath = findGoogleChromeExecutable();

    if (!this.browser?.connected) {
      this.browser = await puppeteer.launch({
        executablePath,
        headless: this.headless,
        userDataDir: profileDir,
        args: ['--no-first-run', '--no-default-browser-check']
      });
      this.browser.on('disconnected', () => {
        this.browser = null;
        this.page = null;
      });
    }
    if (!this.page || this.page.isClosed()) this.page = await this.browser.newPage();
    return this.page;
  }

  async refresh() {
    if (this.inFlight) return this.inFlight;
    this.inFlight = this.performRefresh().finally(() => { this.inFlight = null; });
    return this.inFlight;
  }

  async performRefresh() {
    try {
      const page = await this.ensurePage();
      const response = await page.goto(OPENAI_HOME_URL, { waitUntil: 'networkidle2', timeout: 60000 });
      if (!response || response.status() >= 400) throw new BalanceReadError('BILLING_PAGE_UNAVAILABLE');
      const pageError = classifyPageUrl(page.url());
      if (pageError) throw new BalanceReadError(pageError);
      if (await pageRequiresAuthentication(page)) throw new BalanceReadError('BILLING_AUTH_REQUIRED');
      const balance = await waitForConfirmedBalance(page);
      const updatedAt = new Date().toISOString();
      this.lastConfirmed = { balance, updatedAt };
      this.state = {
        ok: true,
        currency: 'USD',
        balance,
        source: 'openai_platform_home',
        updatedAt,
        refreshMs: this.refreshMs,
        stale: false,
        authRequired: false
      };
    } catch (error) {
      const safeCodes = new Set([
        'BILLING_SESSION_NOT_CONFIGURED',
        'BILLING_AUTH_REQUIRED',
        'BILLING_PAGE_UNAVAILABLE',
        'GOOGLE_CHROME_NOT_FOUND',
        'BALANCE_NOT_FOUND',
        'BALANCE_AMBIGUOUS'
      ]);
      const code = safeCodes.has(error?.code) ? error.code : 'BILLING_PAGE_UNAVAILABLE';
      this.state = this.lastConfirmed
        ? { ...this.state, ok: true, stale: true, code, authRequired: code === 'BILLING_AUTH_REQUIRED' }
        : this.errorState(code);
    }
    return this.getState();
  }

  async close() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    const browser = this.browser;
    this.browser = null;
    this.page = null;
    if (browser?.connected) await browser.close().catch(() => {});
  }
}

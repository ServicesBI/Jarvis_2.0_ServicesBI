(function () {
  'use strict';
  let debounce = null;
  let lastValue = null;
  chrome.runtime.sendMessage({ type: 'OPENAI_BALANCE_STATUS', stage: 'content_script_loaded', page_url: location.origin + location.pathname });
  function inspect() {
    clearTimeout(debounce);
    debounce = setTimeout(() => {
      try {
        const balance = globalThis.JarvisBalanceParser.readCreditBalance(document);
        if (balance === lastValue) return;
        lastValue = balance;
        chrome.runtime.sendMessage({ type: 'OPENAI_BALANCE_OBSERVED', balance_usd: balance, currency: 'USD', observed_at: new Date().toISOString(), source: 'openai_platform_home' });
      } catch {}
    }, 500);
  }
  if (location.pathname === '/home') inspect();
  const observer = new MutationObserver(inspect);
  if (location.pathname === '/home') observer.observe(document.documentElement, { childList: true, subtree: true, characterData: true });
  setTimeout(() => observer.disconnect(), 120000);
})();

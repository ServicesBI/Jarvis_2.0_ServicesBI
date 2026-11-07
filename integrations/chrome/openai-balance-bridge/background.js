'use strict';
const HOME = 'https://platform.openai.com/home';
const INGEST = 'http://127.0.0.1:8000/api/openai-balance/ingest';
const HEARTBEAT = 'http://127.0.0.1:8000/api/openai-balance/heartbeat';

async function heartbeat(stage) {
  const response = await fetch(HEARTBEAT, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ stage, page_url: HOME }) });
  return response.ok;
}

// A extensao NUNCA cria, abre ou procura abas por conta propria. A causa
// raiz do auto-open real era um lifecycle listener (instalacao/inicializacao
// do navegador) mais um alarme periodico de 5 min que recriavam a aba de
// credit balance sempre que nenhuma existisse. Ambos foram removidos de
// proposito e nao devem voltar. O saldo hoje vem exclusivamente da
// Organization Costs API via OpenAICostsLedgerService; esta extensao so
// reage passivamente a um content script que ja esta rodando numa aba que o
// USUARIO abriu manualmente.
chrome.runtime.onMessage.addListener((message, sender) => {
  if (!sender.tab?.url?.startsWith('https://platform.openai.com/')) return;
  if (message?.type === 'OPENAI_BALANCE_STATUS') {
    void heartbeat(message.stage);
    return;
  }
  if (message?.type !== 'OPENAI_BALANCE_OBSERVED' || !sender.tab.url.startsWith(HOME)) return;
  const payload = { balance_usd: message.balance_usd, currency: message.currency, observed_at: message.observed_at, source: message.source };
  void (async () => {
    await heartbeat('credit_balance_found');
    await heartbeat('ingest_sent');
    try {
      const response = await fetch(INGEST, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      await heartbeat(response.ok ? 'ingest_accepted' : 'ingest_rejected');
    } catch {
      await heartbeat('ingest_rejected').catch(() => {});
    }
  })();
});

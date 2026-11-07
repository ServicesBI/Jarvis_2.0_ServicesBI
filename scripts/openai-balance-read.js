import { OPENAI_HOME_URL, OpenAIBalanceBrowser } from '../integrations/node/openai-balance-browser.module.js';

const collector = new OpenAIBalanceBrowser({ headless: true });
try {
  const state = await collector.refresh();
  if (!state.ok || !Number.isFinite(state.balance)) {
    process.stdout.write(JSON.stringify({ error: state.code || 'BALANCE_COLLECTION_FAILED' }));
    process.exitCode = 1;
  } else {
    process.stdout.write(JSON.stringify({
      balance: state.balance,
      sourceUrl: OPENAI_HOME_URL,
      creditBalanceFound: true
    }));
  }
} finally {
  await collector.close();
}

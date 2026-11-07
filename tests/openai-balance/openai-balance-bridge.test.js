import test from 'node:test';
import assert from 'node:assert/strict';
import '../../integrations/chrome/openai-balance-bridge/parser.js';

const { parseBalanceCards } = globalThis.JarvisBalanceParser;

test('bridge selects only the Credit balance card', () => {
  assert.equal(parseBalanceCards([
    { label: 'September spend', value: '$0.37 / $120.00' },
    { label: 'Credit balance', value: '$4.08' }
  ]), 4.08);
});

test('bridge reports BALANCE_NOT_FOUND without the semantic card', () => {
  assert.throws(
    () => parseBalanceCards([{ label: 'September spend', value: '$0.37 / $120.00' }]),
    /BALANCE_NOT_FOUND/
  );
});

test('bridge accepts decimals and rejects conflicting candidates', () => {
  assert.equal(parseBalanceCards([{ label: 'Credit balance', value: '$17.42' }]), 17.42);
  assert.throws(() => parseBalanceCards([
    { label: 'Credit balance', value: '$4.08' },
    { label: 'Credit balance', value: '$5.00' }
  ]), /BALANCE_AMBIGUOUS/);
});

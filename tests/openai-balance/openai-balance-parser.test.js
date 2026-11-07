import test from 'node:test';
import assert from 'node:assert/strict';
import {
  BalanceReadError,
  OPENAI_HOME_URL,
  parseCreditBalanceEntries
} from '../../integrations/node/openai-balance-browser.module.js';

test('uses OpenAI Platform Home as the primary source', () => {
  assert.equal(OPENAI_HOME_URL, 'https://platform.openai.com/home');
});

test('selects Credit balance card and rejects spend and monthly limit values', () => {
  assert.equal(parseCreditBalanceEntries([
    { label: 'September spend', valueText: '$0.37 / $120.00' },
    { label: 'Credit balance', valueText: '$4.08' }
  ]), 4.08);
});

test('does not fall back to another monetary card when Credit balance is absent', () => {
  assert.throws(
    () => parseCreditBalanceEntries([{ label: 'September spend', valueText: '$0.37 / $120.00' }]),
    error => error instanceof BalanceReadError && error.code === 'BALANCE_NOT_FOUND'
  );
});

test('parses English balance with decimal point', () => {
  assert.equal(parseCreditBalanceEntries([{ label: 'Credit balance', valueText: '$5.09' }]), 5.09);
});

test('parses Portuguese balance with decimal comma', () => {
  assert.equal(parseCreditBalanceEntries([{ label: 'Saldo de crédito da API', valueText: 'US$ 5,09' }]), 5.09);
});

test('parses US and Brazilian thousands separators', () => {
  assert.equal(parseCreditBalanceEntries([{ label: 'API credit balance', valueText: '$1,234.56' }]), 1234.56);
  assert.equal(parseCreditBalanceEntries([{ label: 'Saldo de crédito', valueText: 'US$ 1.234,56' }]), 1234.56);
});

test('rejects a page without a semantic balance label', () => {
  assert.throws(
    () => parseCreditBalanceEntries([{ label: 'Monthly spend', valueText: '$5.09' }]),
    error => error instanceof BalanceReadError && error.code === 'BALANCE_NOT_FOUND'
  );
});

test('rejects two ambiguous balance results', () => {
  assert.throws(
    () => parseCreditBalanceEntries([
      { label: 'Credit balance', valueText: '$5.09' },
      { label: 'API credit balance', valueText: '$7.10' }
    ]),
    error => error instanceof BalanceReadError && error.code === 'BALANCE_AMBIGUOUS'
  );
});

test('accepts a confirmed zero balance', () => {
  assert.equal(parseCreditBalanceEntries([{ label: 'Credit balance', valueText: 'US$ 0.00' }]), 0);
});

test('rejects a negative value', () => {
  assert.throws(
    () => parseCreditBalanceEntries([{ label: 'Credit balance', valueText: 'US$ -5.09' }]),
    error => error instanceof BalanceReadError && error.code === 'BALANCE_NOT_FOUND'
  );
});

test('rejects a currency other than USD', () => {
  assert.throws(
    () => parseCreditBalanceEntries([{ label: 'Credit balance', valueText: 'EUR 5.09' }]),
    error => error instanceof BalanceReadError && error.code === 'BALANCE_NOT_FOUND'
  );
});

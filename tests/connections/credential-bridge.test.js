import test from 'node:test';
import assert from 'node:assert/strict';

import { processBridgeRequest } from '../../integrations/node/connections/credential-bridge.js';


class FakeVault {
  constructor() {
    this.values = new Map();
  }

  async setSecret(secret, { reference }) {
    this.values.set(reference, secret);
    return reference;
  }

  async getSecret(reference) {
    return this.values.has(reference) ? this.values.get(reference) : null;
  }

  async hasSecret(reference) {
    return this.values.has(reference);
  }

  async deleteSecret(reference) {
    return this.values.delete(reference);
  }
}


test('bridge processes set/has/get/delete using a narrow JSON contract', async () => {
  const vault = new FakeVault();
  const reference = 'provider:test';
  const secret = 'test-secret-123';

  assert.deepEqual(
    await processBridgeRequest({ operation: 'has', reference }, vault),
    { ok: true, exists: false },
  );
  assert.deepEqual(
    await processBridgeRequest({ operation: 'set', reference, secret }, vault),
    { ok: true, reference },
  );
  assert.deepEqual(
    await processBridgeRequest({ operation: 'has', reference }, vault),
    { ok: true, exists: true },
  );
  assert.deepEqual(
    await processBridgeRequest({ operation: 'get', reference }, vault),
    { ok: true, secret },
  );
  assert.deepEqual(
    await processBridgeRequest({ operation: 'delete', reference }, vault),
    { ok: true, deleted: true },
  );
  assert.deepEqual(
    await processBridgeRequest({ operation: 'delete', reference }, vault),
    { ok: true, deleted: false },
  );
});

test('bridge rejects unknown operations without echoing request material', async () => {
  const secret = 'test-secret-123';
  await assert.rejects(
    () => processBridgeRequest({ operation: 'unknown', reference: 'provider:test', secret }, new FakeVault()),
    (error) => {
      assert.equal(error.code, 'INVALID_BRIDGE_REQUEST');
      assert.doesNotMatch(String(error.message), new RegExp(secret));
      return true;
    },
  );
});

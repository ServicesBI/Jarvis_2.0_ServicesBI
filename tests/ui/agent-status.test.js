import test from 'node:test';
import assert from 'node:assert/strict';
import '../../public/agent-status.js';

const { projectAgentStatus } = globalThis.AgentStatusView;

test('canonical agent statuses project to their visual contract', () => {
  assert.deepEqual(projectAgentStatus('idle'), { status: 'idle', label: 'IDLE' });
  assert.deepEqual(projectAgentStatus('working'), { status: 'working', label: 'WORKING' });
  assert.deepEqual(projectAgentStatus('waiting'), { status: 'waiting', label: 'WAITING' });
  assert.deepEqual(projectAgentStatus('error'), { status: 'error', label: 'ERROR' });
});

test('non-canonical agent statuses are rejected instead of inferred', () => {
  for (const status of ['online', 'ready', 'offline', 'busy', '', null, undefined]) {
    assert.throws(() => projectAgentStatus(status), RangeError);
  }
});

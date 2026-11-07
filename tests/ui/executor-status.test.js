import test from 'node:test';
import assert from 'node:assert/strict';
// public/executor-status.js e um script isomorfico (sem import/export) para poder
// ser carregado tanto por <script src="executor-status.js"> no navegador quanto
// aqui via node:test. Ele publica sua API em globalThis.ExecutorStatus.
import '../../public/executor-status.js';

const {
  formatProviderStatus,
  getAutoExecutorStatus,
  resolveExecutorStatus,
  createStalenessGuard,
  refreshExecutorStatus,
} = globalThis.ExecutorStatus;

const ONLINE = { status: 'online' };
const OFFLINE = { status: 'offline' };
const COLD_START = {
  status: 'unknown',
  installed: true,
  connected: true,
  authenticated: true,
  operational: false,
  eligible: false,
  entitled: true,
  reason: 'capability_not_validated',
};

function providers({ codex, claude }) {
  return { codex, claude };
}

// ── 1-8: mapeamento puro modo + disponibilidade -> ON/OFF ──

test('1. mode=claude + Claude online -> CLAUDE ON', () => {
  const result = resolveExecutorStatus('claude', providers({ codex: OFFLINE, claude: ONLINE }));
  assert.equal(result.ok, true);
  assert.equal(result.text, 'ONLINE');
});

test('2. mode=codex + Codex online -> CODEX ON', () => {
  const result = resolveExecutorStatus('codex', providers({ codex: ONLINE, claude: OFFLINE }));
  assert.equal(result.ok, true);
});

test('3. mode=auto + Codex online -> AUTO ON', () => {
  const result = resolveExecutorStatus('auto', providers({ codex: ONLINE, claude: OFFLINE }));
  assert.equal(result.ok, true);
});

test('4. mode=auto + Codex offline + Claude online -> AUTO ON', () => {
  const result = resolveExecutorStatus('auto', providers({ codex: OFFLINE, claude: ONLINE }));
  assert.equal(result.ok, true);
});

test('5. mode=auto + ambos offline -> AUTO OFF', () => {
  const result = resolveExecutorStatus('auto', providers({ codex: OFFLINE, claude: OFFLINE }));
  assert.equal(result.ok, false);
});

test('6. mode=claude + Claude offline -> CLAUDE OFF', () => {
  const result = resolveExecutorStatus('claude', providers({ codex: ONLINE, claude: OFFLINE }));
  assert.equal(result.ok, false);
});

test('7. mode=claude + Claude online + Codex offline -> CLAUDE ON', () => {
  const result = resolveExecutorStatus('claude', providers({ codex: OFFLINE, claude: ONLINE }));
  assert.equal(result.ok, true);
});

test('8. mode=codex + Codex online + Claude offline -> CODEX ON', () => {
  const result = resolveExecutorStatus('codex', providers({ codex: ONLINE, claude: OFFLINE }));
  assert.equal(result.ok, true);
});

test('AUTO never picks Claude health while Codex is online (does not relabel AUTO as Claude)', () => {
  const result = getAutoExecutorStatus(providers({ codex: ONLINE, claude: OFFLINE }));
  assert.equal(result, providers({ codex: ONLINE, claude: OFFLINE }).codex);
});

test('formatProviderStatus never invents ON/green for a missing provider entry', () => {
  const result = formatProviderStatus(undefined);
  assert.equal(result.ok, false);
});

test('cold-start Claude shows CHECK (not a false READY/ONLINE) and is not promoted to operational or rendered as an error', () => {
  const result = resolveExecutorStatus(
    'claude',
    providers({ codex: ONLINE, claude: COLD_START }),
  );

  // capability_not_validated must never render as if it were confirmed ready/online:
  // READY here would contradict the neutral (non-green) dot it is paired with.
  assert.deepEqual(result, { text: 'CHECK', tone: 'neutral', ok: false });
  assert.equal(COLD_START.operational, false);
  assert.equal(COLD_START.eligible, false);
});

test('a real Claude operational failure remains an error instead of READY', () => {
  const failed = {
    ...COLD_START,
    reason: 'execution_failed',
  };
  const result = resolveExecutorStatus(
    'claude',
    providers({ codex: ONLINE, claude: failed }),
  );

  assert.deepEqual(result, { text: 'UNKNOWN', tone: 'error', ok: false });
});

// ── 9-10: sem lógica concorrente / mesma fonte, e sem sobrescrita por resposta desatualizada ──

test('9. trocar o modo nao altera os dados de health recebidos (mesmo payload de providers)', () => {
  const payload = providers({ codex: ONLINE, claude: ONLINE });
  const claudeView = resolveExecutorStatus('claude', payload);
  const codexView = resolveExecutorStatus('codex', payload);
  // O mesmo payload de entrada nao e mutado ao trocar o modo de leitura.
  assert.deepEqual(payload, providers({ codex: ONLINE, claude: ONLINE }));
  assert.equal(claudeView.ok, true);
  assert.equal(codexView.ok, true);
});

test('10a. duas chamadas concorrentes: a resposta de uma chamada MAIS ANTIGA nao pode sobrescrever a mais recente, mesmo resolvendo depois', async () => {
  const guard = createStalenessGuard();
  const applied = [];

  // Chamada A comeca primeiro (mode=claude, offline) mas demora para responder.
  const callA = refreshExecutorStatus({
    activeExecutor: 'claude',
    fetchProviders: () => new Promise((resolve) => setTimeout(() => resolve(providers({ codex: ONLINE, claude: OFFLINE })), 30)),
    guard,
    onResult: (status) => applied.push({ from: 'A', status }),
  });

  // Chamada B comeca depois (mode=codex, online) e responde mais rapido.
  const callB = refreshExecutorStatus({
    activeExecutor: 'codex',
    fetchProviders: () => new Promise((resolve) => setTimeout(() => resolve(providers({ codex: ONLINE, claude: OFFLINE })), 5)),
    guard,
    onResult: (status) => applied.push({ from: 'B', status }),
  });

  const [outcomeA, outcomeB] = await Promise.all([callA, callB]);

  assert.equal(outcomeB, 'applied');
  assert.equal(outcomeA, 'stale-discarded');
  assert.deepEqual(applied.map((entry) => entry.from), ['B']);
  assert.equal(applied[0].status.ok, true);
});

test('10b. a resposta mais recente sempre vence mesmo quando chega antes da mais antiga', async () => {
  const guard = createStalenessGuard();
  const applied = [];

  const callA = refreshExecutorStatus({
    activeExecutor: 'claude',
    fetchProviders: () => new Promise((resolve) => setTimeout(() => resolve(providers({ codex: OFFLINE, claude: ONLINE })), 5)),
    guard,
    onResult: (status) => applied.push({ from: 'A', status }),
  });

  const callB = refreshExecutorStatus({
    activeExecutor: 'claude',
    fetchProviders: () => new Promise((resolve) => setTimeout(() => resolve(providers({ codex: OFFLINE, claude: OFFLINE })), 30)),
    guard,
    onResult: (status) => applied.push({ from: 'B', status }),
  });

  await Promise.all([callA, callB]);

  assert.deepEqual(applied.map((entry) => entry.from), ['B']);
  assert.equal(applied[0].status.ok, false);
});

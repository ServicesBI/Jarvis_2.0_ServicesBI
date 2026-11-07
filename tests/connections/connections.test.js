import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  AUTH_TYPES,
  CONNECTION_CATEGORIES,
  CONNECTION_TYPES,
  IMPLEMENTATION_STATUSES,
  PROVIDERS,
  getProviderById,
  getProviders
} from '../../integrations/node/connections/provider-registry.js';
import {
  InMemoryTestCredentialVault,
  UnavailableCredentialVault,
  createCredentialVault
} from '../../integrations/node/connections/credential-vault.js';
import {
  ConnectionManager,
  InMemoryConnectionStore
} from '../../integrations/node/connections/connection-manager.js';

const TEST_DIR = path.dirname(fileURLToPath(import.meta.url));
const REPOSITORY_ROOT = path.resolve(TEST_DIR, '..', '..');

const EXPECTED_PROVIDERS = Object.freeze({
  openai: { name: 'OpenAI', category: 'ai-models' },
  codex: { name: 'Codex', category: 'ai-models' },
  'claude-api': { name: 'Claude API', category: 'ai-models' },
  'claude-code': { name: 'Claude Code', category: 'ai-models' },
  gemini: { name: 'Gemini', category: 'ai-models' },
  'google-workspace': { name: 'Google Workspace', category: 'google-productivity' },
  vscode: { name: 'VS Code', category: 'development' },
  powerbi: { name: 'Power BI', category: 'data-systems' },
  'erp-generic': { name: 'Outros ERPs', category: 'data-systems' }
});

const EXPECTED_CATEGORIES = Object.freeze([
  { id: 'ai-models', name: 'IA E MODELOS' },
  { id: 'google-productivity', name: 'GOOGLE E PRODUTIVIDADE' },
  { id: 'development', name: 'DESENVOLVIMENTO' },
  { id: 'data-systems', name: 'DADOS E SISTEMAS' }
]);

const EXPECTED_STATUS_LABELS = Object.freeze({
  not_configured: 'NÃO CONFIGURADO',
  structure_available: 'ESTRUTURA DISPONÍVEL',
  unavailable: 'INDISPONÍVEL',
  error: 'ERRO'
});

function declarationValues(declaration) {
  const rawValues = Array.isArray(declaration) ? declaration : Object.values(declaration);
  return new Set(rawValues.map((entry) => {
    if (entry && typeof entry === 'object') return entry.id ?? entry.value ?? entry.name;
    return entry;
  }));
}

function makeManager() {
  return new ConnectionManager({
    store: new InMemoryConnectionStore(),
    vault: new InMemoryTestCredentialVault()
  });
}

function resultItems(result, property) {
  if (Array.isArray(result)) return result;
  assert.ok(result && Array.isArray(result[property]), `Expected an array or .${property} array`);
  return result[property];
}

function sensitivePropertyPaths(value, currentPath = '$', found = []) {
  if (Array.isArray(value)) {
    value.forEach((entry, index) => sensitivePropertyPaths(entry, `${currentPath}[${index}]`, found));
    return found;
  }
  if (!value || typeof value !== 'object') return found;

  const forbidden = /^(?:secret|secretReference|apiKey|password|privateKey|clientSecret|accessToken|refreshToken|token)$/i;
  for (const [key, entry] of Object.entries(value)) {
    const entryPath = `${currentPath}.${key}`;
    if (forbidden.test(key)) found.push(entryPath);
    sensitivePropertyPaths(entry, entryPath, found);
  }
  return found;
}

function extractNamedFunction(source, functionName) {
  const signature = new RegExp(`(?:async\\s+)?function\\s+${functionName}\\s*\\(`);
  const match = signature.exec(source);
  assert.ok(match, `Function ${functionName} was not found`);

  const openingBrace = source.indexOf('{', match.index + match[0].length);
  assert.notEqual(openingBrace, -1, `Function ${functionName} has no body`);

  let depth = 0;
  let quote = null;
  let escaped = false;
  let lineComment = false;
  let blockComment = false;

  for (let index = openingBrace; index < source.length; index += 1) {
    const character = source[index];
    const next = source[index + 1];

    if (lineComment) {
      if (character === '\n') lineComment = false;
      continue;
    }
    if (blockComment) {
      if (character === '*' && next === '/') {
        blockComment = false;
        index += 1;
      }
      continue;
    }
    if (quote) {
      if (escaped) {
        escaped = false;
      } else if (character === '\\') {
        escaped = true;
      } else if (character === quote) {
        quote = null;
      }
      continue;
    }
    if (character === '/' && next === '/') {
      lineComment = true;
      index += 1;
      continue;
    }
    if (character === '/' && next === '*') {
      blockComment = true;
      index += 1;
      continue;
    }
    if (character === '\'' || character === '"' || character === '`') {
      quote = character;
      continue;
    }
    if (character === '{') depth += 1;
    if (character === '}') {
      depth -= 1;
      if (depth === 0) return source.slice(match.index, index + 1);
    }
  }

  assert.fail(`Function ${functionName} body is incomplete`);
}

test('provider registry is exact, complete, unique and structurally valid', () => {
  assert.ok(Array.isArray(PROVIDERS));
  assert.equal(PROVIDERS.length, 9);
  assert.deepEqual([...PROVIDERS.map(({ id }) => id)].sort(), Object.keys(EXPECTED_PROVIDERS).sort());
  assert.equal(new Set(PROVIDERS.map(({ id }) => id)).size, PROVIDERS.length);
  assert.equal(new Set(PROVIDERS.map(({ name }) => name)).size, PROVIDERS.length);

  assert.deepEqual(
    CONNECTION_CATEGORIES.map(({ id, name }) => ({ id, name })),
    EXPECTED_CATEGORIES
  );

  const categoryIds = new Set(CONNECTION_CATEGORIES.map(({ id }) => id));
  const connectionTypes = declarationValues(CONNECTION_TYPES);
  const authTypes = declarationValues(AUTH_TYPES);
  const implementationStatuses = declarationValues(IMPLEMENTATION_STATUSES);

  for (const provider of PROVIDERS) {
    const expected = EXPECTED_PROVIDERS[provider.id];
    assert.equal(provider.name, expected.name);
    assert.equal(provider.category, expected.category);
    assert.ok(categoryIds.has(provider.category), `${provider.id} has an unknown category`);
    assert.ok(connectionTypes.has(provider.connectionType), `${provider.id} has an unknown connection type`);
    assert.ok(Array.isArray(provider.authTypes) && provider.authTypes.length > 0);
    provider.authTypes.forEach((authType) => {
      assert.ok(authTypes.has(authType), `${provider.id} has an unknown auth type: ${authType}`);
    });
    assert.ok(Array.isArray(provider.capabilities) && provider.capabilities.length > 0);
    provider.capabilities.forEach((capability) => assert.equal(typeof capability, 'string'));
    assert.equal(typeof provider.description, 'string');
    assert.ok(provider.description.trim().length > 0);
    assert.equal(typeof provider.supportsMultipleAccounts, 'boolean');
    assert.ok(implementationStatuses.has(provider.implementationStatus));
    assert.deepEqual(getProviderById(provider.id), provider);
  }

  assert.deepEqual(getProviders(), PROVIDERS);
  assert.equal(getProviderById('provider-that-does-not-exist'), null);
});

test('explicit test vault implements setSecret/getSecret/hasSecret/deleteSecret CRUD', async () => {
  const vault = new InMemoryTestCredentialVault();
  const reference = 'connections-test-reference';
  const secret = 'connections-test-secret-value';

  assert.equal(await vault.hasSecret(reference), false);
  assert.equal(await vault.setSecret(secret, { reference }), reference);
  assert.equal(await vault.hasSecret(reference), true);
  assert.equal(await vault.getSecret(reference), secret);
  assert.equal(await vault.deleteSecret(reference), true);
  assert.equal(await vault.hasSecret(reference), false);
  assert.equal(await vault.getSecret(reference), null);
});

test('production vault factory never falls back to plaintext or test memory', async () => {
  const vault = createCredentialVault({ platform: 'linux', testMode: false });
  assert.ok(vault instanceof UnavailableCredentialVault);
  assert.ok(!(vault instanceof InMemoryTestCredentialVault));

  await assert.rejects(() => vault.setSecret('must-not-be-stored'));
  await assert.rejects(() => vault.getSecret('missing-reference'));
  await assert.rejects(() => vault.deleteSecret('missing-reference'));

  const availability = await vault.hasSecret('missing-reference').catch((error) => error);
  assert.ok(availability === false || availability instanceof Error);
});

test('connection manager supports two accounts for the same provider without exposing secrets', async () => {
  const manager = makeManager();
  const first = await manager.registerConnection({
    connectionId: 'openai-work',
    providerId: 'openai',
    displayName: 'Trabalho',
    accountHint: 'owner.one@example.com',
    lastVerifiedAt: '2026-08-25T12:00:00.000Z',
    expiresAt: '2026-09-25T12:00:00.000Z'
  }, { secret: 'first-private-value' });
  const second = await manager.registerConnection({
    connectionId: 'openai-personal',
    providerId: 'openai',
    displayName: 'Pessoal',
    accountHint: 'owner.two@example.com'
  }, { secret: 'second-private-value' });

  assert.notEqual(first.connectionId, second.connectionId);
  const connections = resultItems(await manager.listConnections(), 'connections');
  const openAIConnections = connections.filter(({ providerId }) => providerId === 'openai');
  assert.equal(openAIConnections.length, 2);
  assert.equal(new Set(openAIConnections.map(({ connectionId }) => connectionId)).size, 2);
  assert.equal(openAIConnections.find(({ connectionId }) => connectionId === first.connectionId).lastVerifiedAt, '2026-08-25T12:00:00.000Z');
  assert.equal(openAIConnections.find(({ connectionId }) => connectionId === first.connectionId).expiresAt, '2026-09-25T12:00:00.000Z');
  assert.deepEqual(sensitivePropertyPaths(openAIConnections), []);
  assert.doesNotMatch(JSON.stringify(openAIConnections), /first-private-value|second-private-value/);

  const providers = resultItems(await manager.listProviders(), 'providers');
  assert.equal(providers.find(({ id }) => id === 'openai').accountCount, 2);

  assert.equal(await manager.removeConnection(first.connectionId), true);
  const remaining = resultItems(await manager.listConnections(), 'connections');
  assert.equal(remaining.filter(({ providerId }) => providerId === 'openai').length, 1);
});

test('connection manager rejects unknown, invalid and sensitive public metadata', async () => {
  const manager = makeManager();
  const invalidCases = [
    { providerId: 'unknown-provider', displayName: 'Inválida' },
    { connectionId: 'invalid/id', providerId: 'openai', displayName: 'Inválida' },
    { providerId: 'openai', displayName: 'Falsa', status: 'operational' },
    { providerId: 'openai', displayName: 'Data inválida', lastVerifiedAt: 'not-a-date' },
    { providerId: 'openai', displayName: 'Segredo', secretReference: 'must-not-enter-metadata' },
    { providerId: 'openai', displayName: 'Chave', apiKey: 'must-not-enter-metadata' },
    { providerId: 'openai', displayName: 'Token', token: 'must-not-enter-metadata' }
  ];

  for (const metadata of invalidCases) {
    await assert.rejects(
      async () => manager.registerConnection(metadata),
      undefined,
      `Expected invalid metadata to be rejected: ${JSON.stringify(metadata)}`
    );
  }

  assert.equal(resultItems(await manager.listConnections(), 'connections').length, 0);
});

test('configuration frontend renders registry data dynamically with factual states only', () => {
  const html = fs.readFileSync(path.join(REPOSITORY_ROOT, 'public', 'index.html'), 'utf8');
  const script = fs.readFileSync(path.join(REPOSITORY_ROOT, 'public', 'script.js'), 'utf8');
  const panelMatch = html.match(/<section class="config-section" data-config-section-panel="accounts">([\s\S]*?)<\/section>\s*<section class="config-section" data-config-section-panel="models">/i);
  assert.ok(panelMatch, 'Accounts/connections configuration panel was not found');
  const accountsPanel = panelMatch[1];

  assert.match(accountsPanel, /Contas e conexões/i);
  assert.match(accountsPanel, /id="config-connections-hub"/i);
  assert.match(accountsPanel, /id="config-connections-message"/i);
  assert.doesNotMatch(accountsPanel, /id="config-provider-(?:claude|codex|gemini)"/i);

  const hubMatch = accountsPanel.match(/<div[^>]*id="config-connections-hub"[^>]*>([\s\S]*?)<\/div>/i);
  assert.ok(hubMatch, 'Dynamic connections hub container was not found');
  assert.doesNotMatch(hubMatch[1], /<article\b|OpenAI|Codex|Claude|Gemini|Google Workspace|VS Code|Power BI|Outros ERPs/i);

  assert.match(script, /fetchJson\(\s*['"]\/api\/connections\/providers['"]\s*\)/);
  assert.match(script, /const\s+CONNECTION_STATUS_LABELS\s*=\s*(?:Object\.freeze\(\s*)?\{/);
  const statusMapMatch = script.match(/const\s+CONNECTION_STATUS_LABELS\s*=\s*(?:Object\.freeze\(\s*)?\{([\s\S]*?)\}\s*\)?\s*;/);
  assert.ok(statusMapMatch, 'Connections status map was not found');
  const actualStatusLabels = Object.fromEntries(
    [...statusMapMatch[1].matchAll(/([a-z_]+)\s*:\s*['"]([^'"]+)['"]/g)]
      .map(([, key, label]) => [key, label])
  );
  assert.deepEqual(actualStatusLabels, EXPECTED_STATUS_LABELS);

  const renderer = extractNamedFunction(script, 'renderConnectionProviders');
  const cardBuilder = extractNamedFunction(script, 'buildConnectionCard');
  const elementFactory = extractNamedFunction(script, 'createConnectionElement');
  assert.match(renderer, /source(?:\?\.|\.)providers/);
  assert.match(renderer, /replaceChildren\(\s*\)/);
  assert.match(renderer, /buildConnectionCard\(\s*provider\b/);
  assert.match(cardBuilder, /createConnectionElement\(\s*['"]article['"]/);
  assert.match(cardBuilder, /\.disabled\s*=\s*true/);
  assert.match(cardBuilder, /INTEGRAÇÃO PENDENTE/);
  assert.match(elementFactory, /\.textContent\s*=/);
  assert.doesNotMatch(renderer, /\.innerHTML\s*=/);
  assert.doesNotMatch(cardBuilder, /\.innerHTML\s*=/);
  assert.doesNotMatch(renderer, /\b(?:CONECTAD[OA]|OPERACIONAL|ATIV[OA])\b/i);
  assert.doesNotMatch(cardBuilder, /\b(?:CONECTAD[OA]|OPERACIONAL|ATIV[OA])\b/i);
  assert.doesNotMatch(`${renderer}\n${cardBuilder}`, /['"](?:OpenAI|Codex|Claude API|Claude Code|Gemini|Google Workspace|VS Code|Power BI|Outros ERPs)['"]/i);
});

test('voice, chat, balance and memory integration markers remain present', () => {
  const fastApiSource = fs.readFileSync(path.join(REPOSITORY_ROOT, 'app', 'main.py'), 'utf8');
  const apiDirectory = path.join(REPOSITORY_ROOT, 'app', 'api');
  const apiSource = fs.readdirSync(apiDirectory)
    .filter((name) => name.endsWith('.py'))
    .map((name) => fs.readFileSync(path.join(apiDirectory, name), 'utf8'))
    .join('\n');
  const frontendSource = fs.readFileSync(path.join(REPOSITORY_ROOT, 'public', 'script.js'), 'utf8');

  const apiMarkers = [
    /@router\.post\(['"]\/chat['"]\)/,
    /@router\.post\(['"]\/stt['"]\)/,
    /@router\.post\(['"]\/tts['"]\)/,
    /@router\.post\(['"]\/realtime\/session['"]\)/,
    /@router\.get\(['"]\/openai-balance['"]\)/,
    /@router\.get\(['"]\/memory\/status['"]\)/
  ];
  assert.match(fastApiSource, /application\.include_router\(/);
  apiMarkers.forEach((marker) => assert.match(apiSource, marker));

  const frontendMarkers = [
    /async function startRealtime\s*\(/,
    /fetch\(['"]\/api\/chat['"]/,
    /fetch\(['"]\/api\/stt['"]/,
    /fetch\(['"]\/api\/tts['"]/,
    /fetch\(['"]\/api\/openai-balance['"]/
  ];
  frontendMarkers.forEach((marker) => assert.match(frontendSource, marker));
});

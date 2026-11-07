import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { JarvisMemorySystem, atomicWriteFile } from '../../integrations/node/memory/memory-system.js';

function fixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'jarvis-memory-test-'));
  const systemDir = path.join(root, 'system');
  const projectsDir = path.join(root, 'projects');
  const obsidianVault = path.join(root, 'vault');
  fs.mkdirSync(systemDir, { recursive: true });
  fs.mkdirSync(projectsDir, { recursive: true });
  fs.mkdirSync(obsidianVault, { recursive: true });
  const memory = new JarvisMemorySystem({ systemDir, projectsDir, obsidianVault });
  return { root, systemDir, projectsDir, obsidianVault, memory };
}

function prepareLocal(memory) {
  memory.initialize();
  atomicWriteFile(memory.historyFile, '[]');
  atomicWriteFile(path.join(memory.systemDir, 'memory-embeddings.json'), '[]');
}

function cleanup(root) {
  assert.ok(root.startsWith(os.tmpdir()));
  fs.rmSync(root, { recursive: true, force: true });
}

test('atomic writes persist and leave no temporary files', () => {
  const { root } = fixture();
  try {
    const target = path.join(root, 'atomic.json');
    atomicWriteFile(target, '{"ok":true}');
    assert.equal(fs.readFileSync(target, 'utf8'), '{"ok":true}');
    assert.deepEqual(fs.readdirSync(root).filter((name) => name.endsWith('.tmp')), []);
  } finally { cleanup(root); }
});

test('local memory writes, persists and can be recovered through Mega Brain', () => {
  const { root, memory } = fixture();
  try {
    prepareLocal(memory);
    const saved = memory.remember({ content: 'O projeto Atlas usa relatórios financeiros.', category: 'project' });
    assert.ok(saved.id);
    const reloaded = new JarvisMemorySystem({ systemDir: memory.systemDir, projectsDir: memory.projectsDir, obsidianVault: memory.obsidianVault });
    assert.equal(reloaded.readHistory().length, 1);
    reloaded.buildIndex();
    assert.equal(reloaded.recall('projeto Atlas')[0].layer, 'local');
  } finally { cleanup(root); }
});

test('Obsidian notes persist, are indexed and reject traversal', () => {
  const { root, obsidianVault, memory } = fixture();
  try {
    prepareLocal(memory);
    const relative = memory.writeObsidianNote('Projetos/Orion', '# Orion\nDecisão de arquitetura modular.');
    assert.equal(relative, 'Projetos/Orion.md');
    assert.match(fs.readFileSync(path.join(obsidianVault, relative), 'utf8'), /arquitetura/);
    memory.buildIndex();
    assert.equal(memory.recall('Orion arquitetura')[0].layer, 'obsidian');
    assert.throws(() => memory.writeObsidianNote('../escape', 'blocked'), /escapes/);
  } finally { cleanup(root); }
});

test('status remains partial until search and restart proofs exist', () => {
  const { root, memory } = fixture();
  try {
    prepareLocal(memory);
    memory.remember({ content: 'persistência local' });
    memory.writeObsidianNote('Teste', 'recuperação obsidian');
    memory.buildIndex();
    const status = memory.status();
    assert.equal(status.status, 'partial');
    assert.equal(status.activeLayers, 3);
    assert.match(status.megaBrain.reason, /search, reload/);
  } finally { cleanup(root); }
});

test('invalid history and invalid embeddings produce a real local error', () => {
  const { root, memory } = fixture();
  try {
    memory.initialize();
    atomicWriteFile(memory.historyFile, '{invalid');
    atomicWriteFile(path.join(memory.systemDir, 'memory-embeddings.json'), '[]');
    assert.equal(memory.status().local.status, 'error');
    atomicWriteFile(memory.historyFile, '[]');
    atomicWriteFile(path.join(memory.systemDir, 'memory-embeddings.json'), '{invalid');
    const status = memory.status();
    assert.equal(status.local.status, 'error');
    assert.ok(status.local.reason);
  } finally { cleanup(root); }
});

test('initialization creates but never overwrites consolidated memory', () => {
  const { root, memory } = fixture();
  try {
    memory.initialize();
    atomicWriteFile(memory.memoryFile, '# Conteúdo preservado\n');
    const before = fs.readFileSync(memory.memoryFile, 'utf8');
    memory.initialize();
    assert.equal(fs.readFileSync(memory.memoryFile, 'utf8'), before);
  } finally { cleanup(root); }
});

test('persistent index, successful search and reload proof make all layers operational', () => {
  const { root, systemDir, projectsDir, obsidianVault, memory } = fixture();
  try {
    prepareLocal(memory);
    memory.remember({ content: 'Projeto Atlas usa arquitetura modular.' });
    memory.writeObsidianNote('Orion', '# Orion\nConhecimento persistente.');
    assert.equal(memory.buildIndex().items.length, 3);
    assert.equal(memory.search('Atlas').length, 1);
    assert.equal(memory.search('termo-que-nao-existe-xyz').length, 0);
    assert.equal(memory.status().megaBrain.reloadVerified, false);
    const reloaded = new JarvisMemorySystem({ systemDir, projectsDir, obsidianVault });
    const status = reloaded.status();
    assert.equal(status.local.projectContexts, 0);
    assert.equal(status.megaBrain.projects, 0);
    assert.equal(status.megaBrain.loadedFromDisk, true);
    assert.equal(status.megaBrain.reloadVerified, true);
    assert.equal(status.status, 'operational');
    assert.equal(reloaded.search('Atlas').length, 1);
    const temporary = fs.readdirSync(systemDir, { recursive: true }).filter((name) => String(name).endsWith('.tmp'));
    assert.deepEqual(temporary, []);
  } finally { cleanup(root); }
});

test('search without results does not satisfy search proof', () => {
  const { root, memory } = fixture();
  try {
    prepareLocal(memory);
    memory.buildIndex();
    assert.deepEqual(memory.search('ausente-xyz'), []);
    assert.equal(memory.status().megaBrain.searchVerified, false);
  } finally { cleanup(root); }
});

test('invalid persisted index is rejected and aggregate remains partial', () => {
  const { root, memory } = fixture();
  try {
    prepareLocal(memory);
    atomicWriteFile(memory.indexFile, '{"schemaVersion":1,"items":"invalid"}');
    const status = memory.status();
    assert.equal(status.local.status, 'operational');
    assert.equal(status.obsidian.status, 'operational');
    assert.equal(status.megaBrain.status, 'unavailable');
    assert.equal(status.status, 'partial');
    assert.match(status.megaBrain.reason, /invalid/);
  } finally { cleanup(root); }
});

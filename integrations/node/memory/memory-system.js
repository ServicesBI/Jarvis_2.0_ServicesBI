import fs from 'fs';
import path from 'path';
import crypto from 'crypto';

const SCHEMA_VERSION = 1;

function ensureDirectory(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

export function atomicWriteFile(filePath, content) {
  ensureDirectory(path.dirname(filePath));
  const temporary = path.join(
    path.dirname(filePath),
    `.${path.basename(filePath)}.${process.pid}.${crypto.randomUUID()}.tmp`
  );
  try {
    fs.writeFileSync(temporary, content, 'utf8');
    fs.renameSync(temporary, filePath);
  } catch (error) {
    try { if (fs.existsSync(temporary)) fs.unlinkSync(temporary); } catch {}
    throw error;
  }
}

function readJson(filePath, fallback) {
  if (!fs.existsSync(filePath)) return fallback;
  return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

function tokenize(value) {
  return [...new Set(String(value || '')
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .toLowerCase().match(/[a-z0-9_]{2,}/g) || [])];
}

function within(root, candidate) {
  const base = path.resolve(root);
  const target = path.resolve(candidate);
  return target === base || target.startsWith(`${base}${path.sep}`);
}

function safeRelativePath(root, relativePath) {
  const target = path.resolve(root, String(relativePath || ''));
  if (!within(root, target)) throw new Error('Path escapes the configured memory root');
  return target;
}

function normalizeHistory(value) {
  if (Array.isArray(value)) return value;
  if (Array.isArray(value?.entries)) return value.entries;
  if (Array.isArray(value?.history)) return value.history;
  return [];
}

export class JarvisMemorySystem {
  constructor({ systemDir, projectsDir, obsidianVault = null, clock = () => new Date() }) {
    this.systemDir = path.resolve(systemDir);
    this.projectsDir = path.resolve(projectsDir);
    this.obsidianVault = obsidianVault ? path.resolve(obsidianVault) : null;
    this.clock = clock;
    this.historyFile = path.join(this.systemDir, 'JARVIS-HISTORY.json');
    this.memoryFile = path.join(this.systemDir, 'JARVIS-MEMORY.md');
    this.megaDir = path.join(this.systemDir, 'mega-brain');
    this.indexFile = path.join(this.megaDir, 'index.json');
    this.proofsFile = path.join(this.megaDir, 'proofs.json');
    this.instanceId = crypto.randomUUID();
    this.loadedIndexFromDisk = fs.existsSync(this.indexFile);
    this.registerReloadProof();
  }

  initialize() {
    ensureDirectory(this.systemDir);
    ensureDirectory(this.megaDir);
    if (!fs.existsSync(this.memoryFile)) {
      atomicWriteFile(this.memoryFile, '# JARVIS Memory\n\n');
    }
  }

  readProofs() {
    return readJson(this.proofsFile, {});
  }

  writeProofs(patch) {
    const proofs = { ...this.readProofs(), ...patch };
    atomicWriteFile(this.proofsFile, JSON.stringify(proofs, null, 2));
    return proofs;
  }

  registerReloadProof() {
    if (!this.loadedIndexFromDisk || !fs.existsSync(this.proofsFile)) return;
    try {
      const proofs = this.readProofs();
      if (proofs.reindexedByInstance && proofs.reindexedByInstance !== this.instanceId && proofs.searchResultCount > 0) {
        this.writeProofs({ reloadedAt: this.clock().toISOString(), reloadedByInstance: this.instanceId });
      }
    } catch {}
  }

  readHistory() {
    return normalizeHistory(readJson(this.historyFile, []));
  }

  remember({ role = 'user', content, category = 'conversation', source = 'jarvis' }) {
    const text = String(content || '').trim();
    if (!text) throw new Error('Memory content is required');
    const entries = this.readHistory();
    const entry = {
      id: crypto.randomUUID(), role: String(role), content: text.slice(0, 20000),
      category: String(category), source: String(source), ts: this.clock().toISOString()
    };
    entries.push(entry);
    atomicWriteFile(this.historyFile, JSON.stringify(entries, null, 2));
    return entry;
  }

  localDocuments() {
    const documents = this.readHistory().map((entry, position) => ({
      id: entry.id || `history-${position}`,
      layer: 'local', source: 'history', path: null,
      title: `${entry.role || 'memory'} ${position + 1}`,
      content: String(entry.content || ''), updatedAt: entry.ts || null
    }));
    if (fs.existsSync(this.memoryFile)) {
      const stat = fs.statSync(this.memoryFile);
      documents.push({
        id: 'consolidated-memory', layer: 'local', source: 'consolidated', path: null,
        title: 'JARVIS consolidated memory', content: fs.readFileSync(this.memoryFile, 'utf8'),
        updatedAt: stat.mtime.toISOString()
      });
    }
    return documents;
  }

  obsidianDocuments() {
    if (!this.obsidianVault || !fs.existsSync(this.obsidianVault)) return [];
    const documents = [];
    const walk = (dir) => {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        if (entry.name.startsWith('.')) continue;
        const fullPath = path.join(dir, entry.name);
        if (entry.isDirectory()) walk(fullPath);
        else if (entry.isFile() && entry.name.toLowerCase().endsWith('.md')) {
          const stat = fs.statSync(fullPath);
          const relative = path.relative(this.obsidianVault, fullPath).replace(/\\/g, '/');
          documents.push({
            id: `obsidian:${relative}`, layer: 'obsidian', source: 'obsidian', path: relative,
            title: path.basename(entry.name, '.md'), content: fs.readFileSync(fullPath, 'utf8'),
            updatedAt: stat.mtime.toISOString()
          });
        }
      }
    };
    walk(this.obsidianVault);
    return documents;
  }

  writeObsidianNote(relativePath, content) {
    if (!this.obsidianVault) throw new Error('Obsidian vault is not configured');
    ensureDirectory(this.obsidianVault);
    const normalized = String(relativePath || '').replace(/\\/g, '/');
    const notePath = safeRelativePath(this.obsidianVault, normalized.endsWith('.md') ? normalized : `${normalized}.md`);
    atomicWriteFile(notePath, String(content || ''));
    return path.relative(this.obsidianVault, notePath).replace(/\\/g, '/');
  }

  buildIndex() {
    const documents = [...this.localDocuments(), ...this.obsidianDocuments()];
    const items = documents.map(({ content, ...document }) => ({
      ...document,
      preview: content.slice(0, 1200),
      terms: tokenize(`${document.title} ${content}`)
    }));
    const index = { schemaVersion: SCHEMA_VERSION, generatedAt: this.clock().toISOString(), items };
    atomicWriteFile(this.indexFile, JSON.stringify(index, null, 2));
    this.writeProofs({
      reindexedAt: index.generatedAt,
      reindexedByInstance: this.instanceId,
      indexedItems: items.length,
      searchAt: null,
      searchResultCount: 0,
      reloadedAt: null,
      reloadedByInstance: null
    });
    return index;
  }

  readIndex() {
    const index = readJson(this.indexFile, { schemaVersion: SCHEMA_VERSION, generatedAt: null, items: [] });
    if (index.schemaVersion !== SCHEMA_VERSION || !Array.isArray(index.items)) throw new Error('Mega Brain index is invalid');
    if (index.items.some((item) => !item || typeof item.id !== 'string' || !Array.isArray(item.terms))) {
      throw new Error('Mega Brain index contains invalid items');
    }
    return index;
  }

  recall(query, { limit = 8, layers = ['local', 'obsidian'] } = {}) {
    const terms = tokenize(query);
    if (!terms.length) return [];
    let index = this.readIndex();
    if (!index.items.length) index = this.buildIndex();
    return index.items
      .filter((item) => layers.includes(item.layer))
      .map((item) => {
        const matches = terms.filter((term) => item.terms.includes(term));
        return { ...item, score: matches.length / terms.length };
      })
      .filter((item) => item.score > 0)
      .sort((a, b) => b.score - a.score || String(b.updatedAt || '').localeCompare(String(a.updatedAt || '')))
      .slice(0, Math.max(1, Math.min(Number(limit) || 8, 25)))
      .map(({ terms: ignored, ...item }) => item);
  }

  search(query, options = {}) {
    const results = this.recall(query, options);
    if (results.length > 0) {
      this.writeProofs({ searchAt: this.clock().toISOString(), searchResultCount: results.length });
    }
    return results.map(({ preview, ...item }) => item);
  }

  probeStorage(dir) {
    const probe = path.join(dir, `.jarvis-memory-probe.${process.pid}.${crypto.randomUUID()}.tmp`);
    try {
      atomicWriteFile(probe, 'jarvis-memory-probe');
      return fs.readFileSync(probe, 'utf8') === 'jarvis-memory-probe';
    } finally {
      try { if (fs.existsSync(probe)) fs.unlinkSync(probe); } catch {}
    }
  }

  validateEmbeddings(filePath) {
    const value = readJson(filePath, null);
    if (!Array.isArray(value)) throw new Error('Embeddings must be a JSON array');
    if (value.some((entry) => !entry || !Array.isArray(entry.embedding))) throw new Error('Embeddings contain invalid entries');
    return value.length;
  }

  status() {
    const local = {
      status: 'error', moduleLoaded: true, historyEntries: 0, embeddings: 0,
      consolidated: false, storageVerified: false, projectContexts: 0, reason: null
    };
    try {
      if (!fs.existsSync(this.historyFile)) throw new Error('History file is missing');
      local.historyEntries = this.readHistory().length;
      local.embeddings = this.validateEmbeddings(path.join(this.systemDir, 'memory-embeddings.json'));
      if (!fs.existsSync(this.memoryFile)) throw new Error('Consolidated memory is missing');
      fs.readFileSync(this.memoryFile, 'utf8');
      local.consolidated = true;
      local.storageVerified = this.probeStorage(this.systemDir);
      if (fs.existsSync(this.projectsDir)) {
        const walk = (dir) => fs.readdirSync(dir, { withFileTypes: true }).reduce((count, entry) => {
          const full = path.join(dir, entry.name);
          return count + (entry.isDirectory() ? walk(full) : entry.name.toLowerCase() === 'context.md' ? 1 : 0);
        }, 0);
        local.projectContexts = walk(this.projectsDir);
      }
      local.status = local.storageVerified ? 'operational' : 'partial';
    } catch (error) { local.reason = error.message; }

    const obsidian = {
      status: 'unavailable', moduleLoaded: true, configured: Boolean(this.obsidianVault),
      notes: 0, treeReadable: false, ingestAvailable: false, reason: null
    };
    try {
      if (!this.obsidianVault || !fs.statSync(this.obsidianVault).isDirectory()) throw new Error('Obsidian vault is unavailable');
      obsidian.notes = this.obsidianDocuments().length;
      obsidian.treeReadable = true;
      fs.accessSync(this.obsidianVault, fs.constants.R_OK | fs.constants.W_OK);
      obsidian.ingestAvailable = true;
      obsidian.status = 'operational';
    } catch (error) { obsidian.reason = error.message; }

    const megaBrain = {
      status: 'unavailable', moduleLoaded: true, storageAvailable: false, indexAvailable: false,
      indexedItems: 0, projects: 0, lastIndexed: null, reindexVerified: false,
      searchVerified: false, reloadVerified: false, loadedFromDisk: this.loadedIndexFromDisk,
      schemaVersion: SCHEMA_VERSION, reason: null
    };
    try {
      const index = this.readIndex();
      const proofs = this.readProofs();
      megaBrain.storageAvailable = this.probeStorage(this.megaDir);
      megaBrain.indexAvailable = true;
      megaBrain.indexedItems = index.items.length;
      megaBrain.projects = index.items.filter((item) => item.source === 'project').length;
      megaBrain.lastIndexed = index.generatedAt;
      megaBrain.reindexVerified = Boolean(proofs.reindexedAt && proofs.indexedItems === index.items.length);
      megaBrain.searchVerified = Boolean(proofs.searchAt && proofs.searchResultCount > 0);
      megaBrain.reloadVerified = Boolean(proofs.reloadedAt && proofs.reloadedByInstance !== proofs.reindexedByInstance);
      const complete = megaBrain.storageAvailable && megaBrain.reindexVerified && megaBrain.searchVerified && megaBrain.reloadVerified;
      megaBrain.status = complete ? 'operational' : 'partial';
      if (!complete) {
        const missing = [!megaBrain.reindexVerified && 'reindex', !megaBrain.searchVerified && 'search', !megaBrain.reloadVerified && 'reload'].filter(Boolean);
        megaBrain.reason = `Pending proof: ${missing.join(', ')}`;
      }
    } catch (error) { megaBrain.reason = error.message; }

    const layers = [local, obsidian, megaBrain];
    const operational = layers.filter((layer) => layer.status === 'operational').length;
    const activeLayers = layers.filter((layer) => layer.status !== 'unavailable' && layer.status !== 'error').length;
    return {
      status: operational === 3 ? 'operational' : activeLayers ? 'partial' : 'unavailable',
      activeLayers, totalLayers: 3, local, obsidian, megaBrain
    };
  }
}

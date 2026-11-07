import crypto from 'crypto';
import fs from 'fs';
import path from 'path';
import {
  CONNECTION_CATEGORIES,
  IMPLEMENTATION_STATUSES,
  IMPLEMENTATION_STATUS_LABELS,
  PROVIDERS
} from './provider-registry.js';
import { createCredentialVault } from './credential-vault.js';

const STORE_SCHEMA_VERSION = 1;
const CONNECTION_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$/;
const ALLOWED_METADATA_FIELDS = new Set([
  'connectionId',
  'providerId',
  'displayName',
  'accountHint',
  'status',
  'scopes',
  'lastVerifiedAt',
  'expiresAt'
]);
const ALLOWED_INTERNAL_FIELDS = new Set([
  ...ALLOWED_METADATA_FIELDS,
  'secretReference',
  'createdAt',
  'updatedAt'
]);
const ALLOWED_STATUSES = new Set(Object.values(IMPLEMENTATION_STATUSES));

function connectionError(code, cause) {
  const error = new Error(code);
  error.name = 'ConnectionManagerError';
  error.code = code;
  if (cause) error.cause = cause;
  return error;
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function writeMetadata(filePath, content) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, content, { encoding: 'utf8', mode: 0o600 });
}

function assertPlainObject(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw connectionError('INVALID_CONNECTION_METADATA');
  }
}

function isSensitiveField(field) {
  const normalized = String(field || '').replace(/[^a-z0-9]/gi, '').toLowerCase();
  return /secret|token|password|passphrase|apikey|privatekey|authorization|cookie|credential|dotenv/.test(normalized);
}

function assertPublicMetadataFields(metadata) {
  for (const field of Object.keys(metadata)) {
    if (isSensitiveField(field)) throw connectionError('SENSITIVE_CONNECTION_METADATA_REJECTED');
    if (!ALLOWED_METADATA_FIELDS.has(field)) throw connectionError('UNKNOWN_CONNECTION_METADATA_FIELD');
  }
}

function normalizeText(value, field, { required = false, maxLength = 160 } = {}) {
  const text = String(value ?? '').trim();
  if ((required && !text) || text.length > maxLength || /[\u0000-\u001f\u007f]/.test(text)) {
    throw connectionError(`INVALID_${field.toUpperCase()}`);
  }
  return text;
}

function normalizeScopes(scopes) {
  if (scopes === undefined) return [];
  if (!Array.isArray(scopes) || scopes.length > 50) throw connectionError('INVALID_CONNECTION_SCOPES');
  const normalized = scopes.map((scope) => normalizeText(scope, 'connection_scope', { required: true, maxLength: 240 }));
  return [...new Set(normalized)];
}

function normalizeOptionalIso(value, field) {
  if (value === undefined || value === null) return null;
  if (typeof value !== 'string' || !value.trim()) throw connectionError(`INVALID_${field.toUpperCase()}`);
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) throw connectionError(`INVALID_${field.toUpperCase()}`);
  return date.toISOString();
}

function maskAccountHint(value) {
  const hint = String(value || '').trim();
  if (!hint) return null;
  const at = hint.indexOf('@');
  if (at > 0 && at < hint.length - 1) {
    return `${hint.slice(0, 1)}***@${hint.slice(at + 1)}`;
  }
  if (hint.length <= 4) return '*'.repeat(hint.length);
  return `${hint.slice(0, 2)}***${hint.slice(-2)}`;
}

function validateInternalRecord(record) {
  assertPlainObject(record);
  for (const field of Object.keys(record)) {
    if (!ALLOWED_INTERNAL_FIELDS.has(field)) throw connectionError('INVALID_STORED_CONNECTION_METADATA');
  }
  if (!CONNECTION_ID_PATTERN.test(String(record.connectionId || ''))) {
    throw connectionError('INVALID_STORED_CONNECTION_METADATA');
  }
  if (!String(record.providerId || '').trim()) throw connectionError('INVALID_STORED_CONNECTION_METADATA');
  if (record.secretReference !== null && record.secretReference !== undefined &&
      !CONNECTION_ID_PATTERN.test(String(record.secretReference))) {
    throw connectionError('INVALID_STORED_CONNECTION_METADATA');
  }
  normalizeOptionalIso(record.lastVerifiedAt, 'last_verified_at');
  normalizeOptionalIso(record.expiresAt, 'expires_at');
  return record;
}

function safeConnection(record) {
  return {
    connectionId: record.connectionId,
    providerId: record.providerId,
    displayName: record.displayName,
    accountHint: record.accountHint || null,
    status: ALLOWED_STATUSES.has(record.status) ? record.status : IMPLEMENTATION_STATUSES.ERROR,
    statusLabel: IMPLEMENTATION_STATUS_LABELS[record.status] || IMPLEMENTATION_STATUS_LABELS[IMPLEMENTATION_STATUSES.ERROR],
    scopes: Array.isArray(record.scopes) ? [...record.scopes] : [],
    lastVerifiedAt: record.lastVerifiedAt || null,
    expiresAt: record.expiresAt || null,
    createdAt: record.createdAt || null,
    updatedAt: record.updatedAt || null
  };
}

export function resolveConnectionMetadataFile(localAppData = process.env.LOCALAPPDATA) {
  if (!localAppData) throw connectionError('LOCAL_APP_DATA_UNAVAILABLE');
  return path.resolve(localAppData, 'ServicesBI_Jarvis', 'connections', 'connections.json');
}

export class InMemoryConnectionStore {
  constructor(initialRecords = []) {
    this.records = initialRecords.map((record) => clone(validateInternalRecord(record)));
    this.kind = 'in_memory_metadata';
    this.isAvailable = true;
  }

  list() {
    return clone(this.records);
  }

  upsert(record) {
    validateInternalRecord(record);
    const index = this.records.findIndex((item) => item.connectionId === record.connectionId);
    if (index >= 0) this.records[index] = clone(record);
    else this.records.push(clone(record));
    return clone(record);
  }

  remove(connectionId) {
    const index = this.records.findIndex((item) => item.connectionId === connectionId);
    if (index < 0) return false;
    this.records.splice(index, 1);
    return true;
  }
}

export const InMemoryConnectionMetadataStore = InMemoryConnectionStore;

export class LocalConnectionStore {
  constructor({ filePath = resolveConnectionMetadataFile() } = {}) {
    this.filePath = path.resolve(filePath);
    this.kind = 'local_app_data_metadata';
    this.isAvailable = true;
  }

  list() {
    if (!fs.existsSync(this.filePath)) return [];
    let parsed;
    try {
      parsed = JSON.parse(fs.readFileSync(this.filePath, 'utf8'));
    } catch (error) {
      throw connectionError('CONNECTION_METADATA_STORE_INVALID', error);
    }
    if (parsed?.schemaVersion !== STORE_SCHEMA_VERSION || !Array.isArray(parsed.connections)) {
      throw connectionError('CONNECTION_METADATA_STORE_INVALID');
    }
    return parsed.connections.map((record) => clone(validateInternalRecord(record)));
  }

  _write(records) {
    for (const record of records) validateInternalRecord(record);
    writeMetadata(this.filePath, JSON.stringify({ schemaVersion: STORE_SCHEMA_VERSION, connections: records }, null, 2));
  }

  upsert(record) {
    validateInternalRecord(record);
    const records = this.list();
    const index = records.findIndex((item) => item.connectionId === record.connectionId);
    if (index >= 0) records[index] = clone(record);
    else records.push(clone(record));
    this._write(records);
    return clone(record);
  }

  remove(connectionId) {
    const records = this.list();
    const filtered = records.filter((record) => record.connectionId !== connectionId);
    if (filtered.length === records.length) return false;
    this._write(filtered);
    return true;
  }
}

export class UnavailableConnectionStore {
  constructor(reason = 'CONNECTION_METADATA_STORE_UNAVAILABLE') {
    this.kind = 'unavailable';
    this.isAvailable = false;
    this.reason = reason;
  }

  list() {
    return [];
  }

  upsert() {
    throw connectionError(this.reason);
  }

  remove() {
    throw connectionError(this.reason);
  }
}

export class ConnectionManager {
  constructor({
    store,
    vault,
    registry = PROVIDERS,
    categories = CONNECTION_CATEGORIES,
    clock = () => new Date()
  } = {}) {
    if (!store || typeof store.list !== 'function' || typeof store.upsert !== 'function' || typeof store.remove !== 'function') {
      throw connectionError('CONNECTION_METADATA_STORE_REQUIRED');
    }
    if (!vault || typeof vault.setSecret !== 'function' || typeof vault.deleteSecret !== 'function') {
      throw connectionError('CREDENTIAL_VAULT_REQUIRED');
    }
    this.store = store;
    this.vault = vault;
    this.registry = registry;
    this.categories = categories;
    this.clock = clock;
    this.providerById = new Map(registry.map((provider) => [provider.id, provider]));
    this.categoryById = new Map(categories.map((category) => [category.id, category]));
  }

  _now() {
    const value = this.clock();
    const date = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(date.getTime())) throw connectionError('INVALID_CONNECTION_CLOCK');
    return date.toISOString();
  }

  _records() {
    return this.store.list().filter((record) => this.providerById.has(record.providerId));
  }

  listCategories() {
    return this.categories.map((category) => ({ ...category }));
  }

  listProviders() {
    const records = this._records();
    return this.registry.map((provider) => {
      const category = this.categoryById.get(provider.category);
      const providerRecords = records.filter((record) => record.providerId === provider.id);
      const lastCheckedAt = providerRecords
        .map((record) => record.lastVerifiedAt)
        .filter(Boolean)
        .sort((left, right) => right.localeCompare(left))[0] || null;
      return {
        ...provider,
        authTypes: [...provider.authTypes],
        capabilities: [...provider.capabilities],
        categoryLabel: category?.name || provider.category,
        accountCount: providerRecords.length,
        lastCheckedAt,
        statusLabel: IMPLEMENTATION_STATUS_LABELS[provider.implementationStatus]
      };
    });
  }

  listConnections() {
    return this._records().map(safeConnection);
  }

  getStatus() {
    const providers = this.listProviders();
    const accountCount = providers.reduce((sum, provider) => sum + provider.accountCount, 0);
    return {
      status: IMPLEMENTATION_STATUSES.STRUCTURE_AVAILABLE,
      statusLabel: IMPLEMENTATION_STATUS_LABELS[IMPLEMENTATION_STATUSES.STRUCTURE_AVAILABLE],
      providerCount: providers.length,
      accountCount,
      metadataStoreAvailable: this.store.isAvailable !== false,
      secureVaultAvailable: this.vault.isAvailable === true,
      providers: providers.map((provider) => ({
        providerId: provider.id,
        implementationStatus: provider.implementationStatus,
        statusLabel: provider.statusLabel,
        accountCount: provider.accountCount,
        lastCheckedAt: provider.lastCheckedAt
      })),
      checkedAt: this._now()
    };
  }

  async registerConnection(metadata, { secret } = {}) {
    assertPlainObject(metadata);
    assertPublicMetadataFields(metadata);
    const providerId = normalizeText(metadata.providerId, 'provider_id', { required: true, maxLength: 80 });
    const provider = this.providerById.get(providerId);
    if (!provider) throw connectionError('UNKNOWN_CONNECTION_PROVIDER');

    const connectionId = metadata.connectionId
      ? normalizeText(metadata.connectionId, 'connection_id', { required: true, maxLength: 160 })
      : `connection_${crypto.randomUUID()}`;
    if (!CONNECTION_ID_PATTERN.test(connectionId)) throw connectionError('INVALID_CONNECTION_ID');

    const records = this._records();
    if (records.some((record) => record.connectionId === connectionId)) {
      throw connectionError('CONNECTION_ID_ALREADY_EXISTS');
    }
    if (!provider.supportsMultipleAccounts && records.some((record) => record.providerId === providerId)) {
      throw connectionError('PROVIDER_DOES_NOT_SUPPORT_MULTIPLE_ACCOUNTS');
    }

    const status = metadata.status || IMPLEMENTATION_STATUSES.NOT_CONFIGURED;
    if (!ALLOWED_STATUSES.has(status)) throw connectionError('INVALID_CONNECTION_STATUS');
    const now = this._now();
    let secretReference = null;

    if (secret !== undefined) {
      if (typeof secret !== 'string' || !secret.length) throw connectionError('INVALID_CREDENTIAL_VALUE');
      secretReference = await this.vault.setSecret(secret);
    }

    const record = {
      connectionId,
      providerId,
      displayName: normalizeText(
        metadata.displayName === undefined ? provider.name : metadata.displayName,
        'display_name',
        { required: true, maxLength: 100 }
      ),
      accountHint: maskAccountHint(normalizeText(metadata.accountHint, 'account_hint', { maxLength: 200 })),
      status,
      scopes: normalizeScopes(metadata.scopes),
      lastVerifiedAt: normalizeOptionalIso(metadata.lastVerifiedAt, 'last_verified_at'),
      expiresAt: normalizeOptionalIso(metadata.expiresAt, 'expires_at'),
      secretReference,
      createdAt: now,
      updatedAt: now
    };

    try {
      this.store.upsert(record);
    } catch (error) {
      if (secretReference) {
        try { await this.vault.deleteSecret(secretReference); } catch {}
      }
      throw error;
    }
    return safeConnection(record);
  }

  async removeConnection(connectionId) {
    const normalized = normalizeText(connectionId, 'connection_id', { required: true, maxLength: 160 });
    if (!CONNECTION_ID_PATTERN.test(normalized)) throw connectionError('INVALID_CONNECTION_ID');
    const record = this._records().find((item) => item.connectionId === normalized);
    if (!record) return false;
    if (record.secretReference) await this.vault.deleteSecret(record.secretReference);
    return this.store.remove(normalized);
  }

  async registerAccount(metadata, options) {
    return this.registerConnection(metadata, options);
  }

  async removeAccount(connectionId) {
    return this.removeConnection(connectionId);
  }
}

export function createConnectionManager({
  localAppData = process.env.LOCALAPPDATA,
  platform = process.platform,
  clock
} = {}) {
  const vault = createCredentialVault({ localAppData, platform });
  const store = localAppData
    ? new LocalConnectionStore({ filePath: resolveConnectionMetadataFile(localAppData) })
    : new UnavailableConnectionStore();
  return new ConnectionManager({ store, vault, clock });
}

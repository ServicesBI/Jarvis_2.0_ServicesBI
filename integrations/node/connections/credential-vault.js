import crypto from 'crypto';
import path from 'path';
import { WindowsDpapiCredentialVault } from './windows-dpapi-vault.js';

function unavailableError(reason = 'SECURE_VAULT_UNAVAILABLE') {
  const error = new Error(reason);
  error.name = 'CredentialVaultError';
  error.code = reason;
  return error;
}

function parseSetArguments(valueOrReference, optionsOrValue) {
  if (typeof optionsOrValue === 'string') {
    return { reference: String(valueOrReference || '').trim(), secret: optionsOrValue };
  }
  const options = optionsOrValue && typeof optionsOrValue === 'object' ? optionsOrValue : {};
  return {
    reference: String(options.reference || `test_cred_${crypto.randomUUID()}`).trim(),
    secret: valueOrReference
  };
}

export class CredentialVault {
  async set() {
    throw unavailableError('CREDENTIAL_VAULT_NOT_IMPLEMENTED');
  }

  async get() {
    throw unavailableError('CREDENTIAL_VAULT_NOT_IMPLEMENTED');
  }

  async delete() {
    throw unavailableError('CREDENTIAL_VAULT_NOT_IMPLEMENTED');
  }

  async has() {
    throw unavailableError('CREDENTIAL_VAULT_NOT_IMPLEMENTED');
  }

  async setSecret(secret, options) {
    return this.set(secret, options);
  }

  async getSecret(reference) {
    return this.get(reference);
  }

  async deleteSecret(reference) {
    return this.delete(reference);
  }

  async hasSecret(reference) {
    return this.has(reference);
  }
}

export class InMemoryTestCredentialVault extends CredentialVault {
  constructor() {
    super();
    this.values = new Map();
    this.kind = 'in_memory_test_only';
    this.isAvailable = true;
    this.isTestOnly = true;
  }

  async set(valueOrReference, optionsOrValue) {
    const { reference, secret } = parseSetArguments(valueOrReference, optionsOrValue);
    if (!reference || typeof secret !== 'string' || !secret.length) {
      throw unavailableError('INVALID_CREDENTIAL_VALUE');
    }
    this.values.set(reference, secret);
    return reference;
  }

  async get(reference) {
    return this.values.has(reference) ? this.values.get(reference) : null;
  }

  async delete(reference) {
    return this.values.delete(reference);
  }

  async has(reference) {
    return this.values.has(reference);
  }
}

export class UnavailableCredentialVault extends CredentialVault {
  constructor(reason = 'SECURE_VAULT_UNAVAILABLE') {
    super();
    this.reason = reason;
    this.kind = 'unavailable';
    this.isAvailable = false;
    this.isTestOnly = false;
  }

  async set() {
    throw unavailableError(this.reason);
  }

  async get() {
    throw unavailableError(this.reason);
  }

  async delete() {
    throw unavailableError(this.reason);
  }

  async has() {
    throw unavailableError(this.reason);
  }
}

export function createCredentialVault({
  testMode = false,
  platform = process.platform,
  localAppData = process.env.LOCALAPPDATA
} = {}) {
  if (testMode === true) return new InMemoryTestCredentialVault();
  if (testMode !== false) throw unavailableError('INVALID_VAULT_MODE');

  if (platform === 'win32' && localAppData) {
    return new WindowsDpapiCredentialVault({
      platform,
      rootDir: path.join(localAppData, 'ServicesBI_Jarvis', 'credentials')
    });
  }

  return new UnavailableCredentialVault('SECURE_VAULT_UNAVAILABLE');
}

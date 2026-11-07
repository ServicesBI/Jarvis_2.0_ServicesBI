import crypto from 'crypto';
import fs from 'fs';
import path from 'path';
import { spawn } from 'child_process';
import { fileURLToPath } from 'url';

const MODULE_DIR = path.dirname(fileURLToPath(import.meta.url));
const DPAPI_HELPER = path.join(MODULE_DIR, 'windows-dpapi-helper.ps1');
const MAX_SECRET_LENGTH = 64 * 1024;
const MAX_HELPER_OUTPUT = 256 * 1024;
const REFERENCE_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$/;

function vaultError(code, cause) {
  const error = new Error(code);
  error.name = 'CredentialVaultError';
  error.code = code;
  if (cause) error.cause = cause;
  return error;
}

function assertReference(reference) {
  const normalized = String(reference || '').trim();
  if (!REFERENCE_PATTERN.test(normalized)) throw vaultError('INVALID_CREDENTIAL_REFERENCE');
  return normalized;
}

function assertSecret(secret) {
  if (typeof secret !== 'string' || !secret.length || secret.length > MAX_SECRET_LENGTH) {
    throw vaultError('INVALID_CREDENTIAL_VALUE');
  }
  return secret;
}

function parseSetArguments(valueOrReference, optionsOrValue) {
  if (typeof optionsOrValue === 'string') {
    return {
      reference: assertReference(valueOrReference),
      secret: assertSecret(optionsOrValue)
    };
  }

  const options = optionsOrValue && typeof optionsOrValue === 'object' ? optionsOrValue : {};
  return {
    reference: options.reference ? assertReference(options.reference) : `cred_${crypto.randomUUID()}`,
    secret: assertSecret(valueOrReference)
  };
}

function writeEncryptedValue(fileSystem, filePath, value) {
  fileSystem.mkdirSync(path.dirname(filePath), { recursive: true });
  const temporaryPath = `${filePath}.${crypto.randomUUID()}.tmp`;
  try {
    fileSystem.writeFileSync(temporaryPath, value, { encoding: 'utf8', mode: 0o600 });
    fileSystem.renameSync(temporaryPath, filePath);
  } catch (error) {
    try {
      if (fileSystem.existsSync(temporaryPath)) fileSystem.unlinkSync(temporaryPath);
    } catch {}
    throw vaultError('CREDENTIAL_VAULT_WRITE_FAILED', error);
  }
}

function defaultPowerShellPath() {
  const systemRoot = process.env.SystemRoot || 'C:\\Windows';
  return path.join(systemRoot, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
}

export function resolveWindowsVaultDirectory(localAppData = process.env.LOCALAPPDATA) {
  if (!localAppData) throw vaultError('LOCAL_APP_DATA_UNAVAILABLE');
  return path.resolve(localAppData, 'ServicesBI_Jarvis', 'credentials');
}

export class WindowsDpapiCredentialVault {
  constructor({
    rootDir = resolveWindowsVaultDirectory(),
    platform = process.platform,
    spawnProcess = spawn,
    powerShellPath = defaultPowerShellPath(),
    fileSystem = fs,
    helperTimeoutMs = 15_000
  } = {}) {
    this.rootDir = path.resolve(rootDir);
    this.platform = platform;
    this.spawnProcess = spawnProcess;
    this.powerShellPath = path.resolve(powerShellPath);
    this.fileSystem = fileSystem;
    this.helperTimeoutMs = helperTimeoutMs;
    this.helperPath = DPAPI_HELPER;
    this.kind = 'windows_dpapi_current_user';
    this.isAvailable = platform === 'win32';
    this.isTestOnly = false;
  }

  _assertAvailable() {
    if (this.platform !== 'win32') throw vaultError('SECURE_VAULT_UNAVAILABLE');
    if (!this.fileSystem.existsSync(this.helperPath)) throw vaultError('DPAPI_HELPER_UNAVAILABLE');
  }

  _pathFor(reference) {
    const normalized = assertReference(reference);
    const fileName = `${crypto.createHash('sha256').update(normalized, 'utf8').digest('hex')}.dpapi`;
    return path.join(this.rootDir, fileName);
  }

  _runHelper(action, value) {
    this._assertAvailable();
    return new Promise((resolve, reject) => {
      const child = this.spawnProcess(
        this.powerShellPath,
        ['-NoLogo', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', this.helperPath],
        {
          shell: false,
          windowsHide: true,
          stdio: ['pipe', 'pipe', 'pipe']
        }
      );

      let stdout = '';
      let stderrSize = 0;
      let settled = false;
      let timeoutHandle;
      const finish = (callback) => {
        if (settled) return;
        settled = true;
        if (timeoutHandle) clearTimeout(timeoutHandle);
        callback();
      };
      timeoutHandle = setTimeout(() => {
        finish(() => {
          child.kill();
          reject(vaultError('DPAPI_HELPER_TIMEOUT'));
        });
      }, this.helperTimeoutMs);

      child.stdout.setEncoding('utf8');
      child.stderr.setEncoding('utf8');
      child.stdout.on('data', (chunk) => {
        stdout += chunk;
        if (stdout.length > MAX_HELPER_OUTPUT) {
          child.kill();
          finish(() => reject(vaultError('DPAPI_HELPER_OUTPUT_LIMIT')));
        }
      });
      child.stderr.on('data', (chunk) => {
        stderrSize += chunk.length;
        if (stderrSize > MAX_HELPER_OUTPUT) {
          child.kill();
          finish(() => reject(vaultError('DPAPI_HELPER_OUTPUT_LIMIT')));
        }
      });
      child.on('error', (error) => finish(() => reject(vaultError('DPAPI_HELPER_FAILED', error))));
      child.on('close', (code) => {
        if (code !== 0) return finish(() => reject(vaultError('DPAPI_HELPER_FAILED')));
        finish(() => resolve(stdout));
      });

      child.stdin.on('error', (error) => finish(() => reject(vaultError('DPAPI_HELPER_FAILED', error))));
      child.stdin.end(JSON.stringify({ action, value }), 'utf8');
    });
  }

  async set(valueOrReference, optionsOrValue) {
    const { reference, secret } = parseSetArguments(valueOrReference, optionsOrValue);
    const encrypted = await this._runHelper('protect', secret);
    if (!encrypted || encrypted.length > MAX_HELPER_OUTPUT) throw vaultError('DPAPI_PROTECTION_FAILED');
    writeEncryptedValue(this.fileSystem, this._pathFor(reference), encrypted);
    return reference;
  }

  async get(reference) {
    const filePath = this._pathFor(reference);
    if (!this.fileSystem.existsSync(filePath)) return null;
    const encrypted = this.fileSystem.readFileSync(filePath, 'utf8');
    if (!encrypted || encrypted.length > MAX_HELPER_OUTPUT) throw vaultError('INVALID_DPAPI_PAYLOAD');
    return this._runHelper('unprotect', encrypted);
  }

  async delete(reference) {
    const filePath = this._pathFor(reference);
    if (!this.fileSystem.existsSync(filePath)) return false;
    this.fileSystem.unlinkSync(filePath);
    return true;
  }

  async has(reference) {
    return this.fileSystem.existsSync(this._pathFor(reference));
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

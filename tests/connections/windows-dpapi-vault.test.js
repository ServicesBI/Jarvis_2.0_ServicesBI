import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';

import { WindowsDpapiCredentialVault } from '../../integrations/node/connections/windows-dpapi-vault.js';


function helperProcess(output = 'encrypted-payload') {
  const child = new EventEmitter();
  child.stdout = new PassThrough();
  child.stderr = new PassThrough();
  child.stdin = new PassThrough();
  child.stdin.on('finish', () => {
    child.stdout.end(output);
    child.stderr.end();
    queueMicrotask(() => child.emit('close', 0));
  });
  child.kill = () => child.emit('close', 1);
  return child;
}

test('vault set writes in same directory, atomically renames and removes no final value on failure', async () => {
  const calls = [];
  const files = new Set();
  const fileSystem = {
    existsSync(filePath) {
      return String(filePath).endsWith('windows-dpapi-helper.ps1') || files.has(filePath);
    },
    mkdirSync() {},
    writeFileSync(filePath) {
      calls.push(['write', filePath]);
      files.add(filePath);
    },
    renameSync(source, target) {
      calls.push(['rename', source, target]);
      files.delete(source);
      files.add(target);
    },
    unlinkSync(filePath) {
      calls.push(['unlink', filePath]);
      files.delete(filePath);
    },
    readFileSync() { return 'encrypted-payload'; },
  };
  const vault = new WindowsDpapiCredentialVault({
    platform: 'win32',
    rootDir: 'C:\\vault-test',
    powerShellPath: 'C:\\powershell.exe',
    spawnProcess: () => helperProcess(),
    fileSystem,
    helperTimeoutMs: 1000,
  });

  await vault.setSecret('test-secret-123', { reference: 'provider:test' });

  const write = calls.find(([operation]) => operation === 'write');
  const rename = calls.find(([operation]) => operation === 'rename');
  assert.ok(write, 'encrypted value must first be written to a temporary file');
  assert.ok(rename, 'temporary file must be atomically renamed');
  assert.equal(rename[1], write[1]);
  assert.equal(String(write[1]).startsWith(vault.rootDir), true);
  assert.match(String(write[1]), /\.tmp$/);
  assert.match(String(rename[2]), /\.dpapi$/);
  assert.equal([...files].some((filePath) => String(filePath).endsWith('.tmp')), false);
});

test('vault helper timeout kills the process and returns a safe code', async () => {
  const child = helperProcess();
  child.stdin.removeAllListeners('finish');
  let killed = false;
  child.kill = () => {
    killed = true;
    child.emit('close', 1);
  };
  const vault = new WindowsDpapiCredentialVault({
    platform: 'win32',
    rootDir: 'C:\\vault-test',
    powerShellPath: 'C:\\powershell.exe',
    spawnProcess: () => child,
    fileSystem: {
      existsSync: () => true,
      mkdirSync() {},
      writeFileSync() {},
      renameSync() {},
      unlinkSync() {},
      readFileSync() { return ''; },
    },
    helperTimeoutMs: 5,
  });

  await assert.rejects(
    () => vault.setSecret('test-secret-123', { reference: 'provider:test' }),
    (error) => error.code === 'DPAPI_HELPER_TIMEOUT',
  );
  assert.equal(killed, true);
});

test('vault removes the temporary file when atomic rename fails', async () => {
  const files = new Set();
  const removed = [];
  const fileSystem = {
    existsSync(filePath) {
      return String(filePath).endsWith('windows-dpapi-helper.ps1') || files.has(filePath);
    },
    mkdirSync() {},
    writeFileSync(filePath) { files.add(filePath); },
    renameSync() { throw new Error('simulated rename failure'); },
    unlinkSync(filePath) {
      removed.push(filePath);
      files.delete(filePath);
    },
    readFileSync() { return 'encrypted-payload'; },
  };
  const vault = new WindowsDpapiCredentialVault({
    platform: 'win32',
    rootDir: 'C:\\vault-test',
    powerShellPath: 'C:\\powershell.exe',
    spawnProcess: () => helperProcess(),
    fileSystem,
    helperTimeoutMs: 1000,
  });

  await assert.rejects(
    () => vault.setSecret('test-secret-123', { reference: 'provider:test' }),
    (error) => error.code === 'CREDENTIAL_VAULT_WRITE_FAILED',
  );
  assert.equal(removed.length, 1);
  assert.match(String(removed[0]), /\.tmp$/);
  assert.equal(files.size, 0);
});

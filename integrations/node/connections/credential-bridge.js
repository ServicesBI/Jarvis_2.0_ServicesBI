import { fileURLToPath } from 'node:url';

import { createCredentialVault } from './credential-vault.js';


const MAX_REQUEST_LENGTH = 128 * 1024;


function bridgeError(code) {
  const error = new Error(code);
  error.name = 'CredentialBridgeError';
  error.code = code;
  return error;
}


export async function processBridgeRequest(request, vault = createCredentialVault()) {
  if (!request || typeof request !== 'object' || Array.isArray(request)) {
    throw bridgeError('INVALID_BRIDGE_REQUEST');
  }
  const { operation, reference } = request;
  if (typeof operation !== 'string' || typeof reference !== 'string') {
    throw bridgeError('INVALID_BRIDGE_REQUEST');
  }

  if (operation === 'set') {
    if (typeof request.secret !== 'string') throw bridgeError('INVALID_BRIDGE_REQUEST');
    const storedReference = await vault.setSecret(request.secret, { reference });
    return { ok: true, reference: storedReference };
  }
  if (operation === 'get') {
    return { ok: true, secret: await vault.getSecret(reference) };
  }
  if (operation === 'has') {
    return { ok: true, exists: await vault.hasSecret(reference) };
  }
  if (operation === 'delete') {
    return { ok: true, deleted: await vault.deleteSecret(reference) };
  }
  throw bridgeError('INVALID_BRIDGE_REQUEST');
}


async function readRequest() {
  let input = '';
  process.stdin.setEncoding('utf8');
  for await (const chunk of process.stdin) {
    input += chunk;
    if (input.length > MAX_REQUEST_LENGTH) throw bridgeError('INVALID_BRIDGE_REQUEST');
  }
  try {
    return JSON.parse(input);
  } catch {
    throw bridgeError('INVALID_BRIDGE_REQUEST');
  }
}


async function main() {
  try {
    const response = await processBridgeRequest(await readRequest());
    process.stdout.write(JSON.stringify(response));
  } catch (error) {
    const code = typeof error?.code === 'string' ? error.code : 'CREDENTIAL_BRIDGE_FAILED';
    process.stdout.write(JSON.stringify({ ok: false, error: code }));
    process.exitCode = 1;
  }
}


if (process.argv[1] && fileURLToPath(import.meta.url) === fileURLToPath(new URL(`file:///${process.argv[1].replace(/\\/g, '/')}`))) {
  await main();
}

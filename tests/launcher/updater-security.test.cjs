const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { test } = require('node:test');

test('launcher updater obtains its GitHub token from local configuration', () => {
  const source = readFileSync(join(process.cwd(), 'launcher', 'updater.js'), 'utf8');

  assert.doesNotMatch(source, /github_pat_[A-Za-z0-9_]+/);
  assert.match(source, /JARVIS_UPDATE_GITHUB_TOKEN/);
});

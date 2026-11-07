// JARVIS Launcher updater

const https = require('https');
const fs = require('fs');
const path = require('path');
const os = require('os');
const AdmZip = require('adm-zip');

// ── CONFIG ──
const REPO_OWNER = 'gaahzx';
const REPO_NAME = 'felipe-updates';
const REPO_BRANCH = 'main';

// ── PROTECTED PATHS (nunca sobrescritos no update) ──
const PROTECTED_PATHS = [
  // Dados pessoais do aluno
  '.env',                              // Chave OpenAI
  'Documents and Projects',            // Arquivos criados pelo aluno
  'system/FELIPE-MEMORY.md',           // Memoria personalizada
  'system/FELIPE-HISTORY.json',        // Historico de conversas
  'system/JARVIS-MEMORY.md',           // Memoria do Jarvis
  'system/JARVIS-HISTORY.json',        // Historico do Jarvis
  'system/memory-embeddings.json',     // RAG embeddings
  // Infraestrutura
  'FELIPE-Launcher.exe',               // Auto-atualizacao do .exe e separada
  '.felipe-launcher-config.json',
];

function readUpdateToken(jarvisDir) {
  if (process.env.JARVIS_UPDATE_GITHUB_TOKEN) {
    return process.env.JARVIS_UPDATE_GITHUB_TOKEN.trim();
  }

  try {
    const envText = fs.readFileSync(path.join(jarvisDir, '.env'), 'utf8');
    const line = envText.split(/\r?\n/).find(item => item.trim().startsWith('JARVIS_UPDATE_GITHUB_TOKEN='));
    return line ? line.split('=', 2)[1].trim().replace(/^['"]|['"]$/g, '') : '';
  } catch {
    return '';
  }
}

function githubRequest(urlPath, token, options = {}) {
  return new Promise((resolve, reject) => {
    const reqOptions = {
      hostname: 'api.github.com',
      path: urlPath,
      method: options.method || 'GET',
      headers: {
        'User-Agent': 'FELIPE-Launcher',
        'Accept': 'application/vnd.github.v3+json',
        'Authorization': `Bearer ${token}`,
        ...options.headers,
      },
    };

    https.get(reqOptions, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          try { resolve(JSON.parse(data)); }
          catch { resolve(data); }
        } else {
          reject(new Error(`HTTP ${res.statusCode}: ${data.substring(0, 200)}`));
        }
      });
    }).on('error', reject);
  });
}

function compareVersions(a, b) {
  const pa = a.split('.').map(n => parseInt(n, 10) || 0);
  const pb = b.split('.').map(n => parseInt(n, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const na = pa[i] || 0;
    const nb = pb[i] || 0;
    if (na > nb) return 1;
    if (na < nb) return -1;
  }
  return 0;
}

async function checkForUpdate(jarvisDir) {
  const token = readUpdateToken(jarvisDir);
  if (!token || REPO_OWNER.includes('__')) {
    return { hasUpdate: false, error: 'Updater não configurado' };
  }

  try {
    // Busca VERSION.txt do repo
    const result = await githubRequest(
      `/repos/${REPO_OWNER}/${REPO_NAME}/contents/VERSION.txt?ref=${REPO_BRANCH}`,
      token
    );

    const remoteVersion = Buffer.from(result.content, 'base64').toString().trim();

    // Lê VERSION.txt local
    const localVersionFile = path.join(jarvisDir, 'VERSION.txt');
    let localVersion = '0.0.0';
    if (fs.existsSync(localVersionFile)) {
      localVersion = fs.readFileSync(localVersionFile, 'utf8').trim();
    }

    const hasUpdate = compareVersions(remoteVersion, localVersion) > 0;

    return {
      hasUpdate,
      remoteVersion,
      localVersion,
    };
  } catch (err) {
    console.error('[Updater] Check failed:', err.message);
    return { hasUpdate: false, error: err.message };
  }
}

function downloadZipball(token) {
  return new Promise((resolve, reject) => {
    const tempZip = path.join(os.tmpdir(), `felipe-update-${Date.now()}.zip`);

    function downloadFrom(hostname, pathname, headers) {
      https.get({ hostname, path: pathname, headers }, (res) => {
        // Seguir redirect
        if (res.statusCode === 302 || res.statusCode === 301) {
          const redirect = new URL(res.headers.location);
          downloadFrom(
            redirect.hostname,
            redirect.pathname + redirect.search,
            { 'User-Agent': 'FELIPE-Launcher' }
          );
          return;
        }

        if (res.statusCode !== 200) {
          reject(new Error(`Download falhou: HTTP ${res.statusCode}`));
          return;
        }

        const file = fs.createWriteStream(tempZip);
        res.pipe(file);
        file.on('finish', () => {
          file.close();
          resolve(tempZip);
        });
        file.on('error', reject);
      }).on('error', reject);
    }

    downloadFrom(
      'api.github.com',
      `/repos/${REPO_OWNER}/${REPO_NAME}/zipball/${REPO_BRANCH}`,
      {
        'User-Agent': 'FELIPE-Launcher',
        'Authorization': `Bearer ${token}`,
      }
    );
  });
}

function extractAndApply(zipPath, jarvisDir) {
  const zip = new AdmZip(zipPath);
  const entries = zip.getEntries();

  if (entries.length === 0) throw new Error('Zip vazio');

  // GitHub zipballs têm prefixo "REPO-SHA/"
  const rootPrefix = entries[0].entryName.split('/')[0] + '/';

  let updatedCount = 0;
  let skippedCount = 0;

  for (const entry of entries) {
    if (entry.isDirectory) continue;

    const relativePath = entry.entryName.substring(rootPrefix.length);
    if (!relativePath) continue;

    // Normaliza separadores (zip usa /, Windows usa \)
    const normalizedPath = relativePath.replace(/\//g, path.sep);

    // Verifica se é protegido
    const isProtected = PROTECTED_PATHS.some(p => {
      const normP = p.replace(/\//g, path.sep);
      return normalizedPath === normP || normalizedPath.startsWith(normP + path.sep);
    });

    if (isProtected) {
      skippedCount++;
      continue;
    }

    // Escreve arquivo
    const targetPath = path.join(jarvisDir, normalizedPath);
    const targetDir = path.dirname(targetPath);
    if (!fs.existsSync(targetDir)) {
      fs.mkdirSync(targetDir, { recursive: true });
    }
    fs.writeFileSync(targetPath, entry.getData());
    updatedCount++;
  }

  return { updatedCount, skippedCount };
}

async function applyUpdate(jarvisDir, progressCallback) {
  try {
    const token = readUpdateToken(jarvisDir);
    if (!token) return { success: false, error: 'Updater não configurado' };
    if (progressCallback) progressCallback('Baixando atualização...');
    const zipPath = await downloadZipball(token);

    if (progressCallback) progressCallback('Aplicando atualização...');
    const result = extractAndApply(zipPath, jarvisDir);

    // Limpa zip temporário
    try { fs.unlinkSync(zipPath); } catch {}

    if (progressCallback) progressCallback('Concluído!');
    return { success: true, ...result };
  } catch (err) {
    console.error('[Updater] Update failed:', err);
    return { success: false, error: err.message };
  }
}

module.exports = {
  checkForUpdate,
  applyUpdate,
};

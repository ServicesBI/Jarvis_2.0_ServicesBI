const { app, BrowserWindow, ipcMain, shell, dialog } = require('electron');
const path = require('path');
const os = require('os');
const { spawn, execFileSync, execSync } = require('child_process');
const http = require('http');
const updater = require('./updater');

// Detectar pasta do JARVIS:
// - Se rodando via source (launcher/main.js): pai do __dirname
// - Se rodando via .exe portable: pasta onde o .exe está (process.env.PORTABLE_EXECUTABLE_DIR)
// - Fallback: procura run.py subindo diretórios
const fs = require('fs');

// Localiza node.exe no sistema (Electron nao herda PATH completo)
function findNodeExe() {
  const candidates = [
    'C:\\Program Files\\nodejs\\node.exe',
    'C:\\Program Files (x86)\\nodejs\\node.exe',
    path.join(os.homedir(), 'AppData', 'Roaming', 'npm', 'node.exe'),
    path.join(os.homedir(), 'AppData', 'Local', 'Programs', 'nodejs', 'node.exe'),
  ];
  for (const p of candidates) {
    if (fs.existsSync(p)) return p;
  }
  // Tenta via PATH
  try {
    const which = require('child_process').execSync(process.platform === 'win32' ? 'where node' : 'which node', { encoding: 'utf8' });
    const first = which.split('\n')[0].trim();
    if (first && fs.existsSync(first)) return first;
  } catch {}
  return 'node'; // fallback (depende do PATH)
}

// Monta PATH completo do sistema (Electron as vezes vem com PATH reduzido)
function getFullPath() {
  const extras = [
    'C:\\Program Files\\nodejs',
    'C:\\Program Files\\Git\\cmd',
    'C:\\Program Files\\Git\\bin',
    'C:\\Program Files\\Python311',
    'C:\\Program Files\\Python311\\Scripts',
    path.join(os.homedir(), 'AppData', 'Roaming', 'npm'),
  ];
  return extras.join(';') + ';' + (process.env.PATH || '');
}

function findJarvisDir() {
  const HOME = os.homedir();

  // Primeiro: checar config salvo no registry/arquivo (se existe)
  const configFile = path.join(HOME, '.jarvis-launcher-config.json');
  if (fs.existsSync(configFile)) {
    try {
      const cfg = JSON.parse(fs.readFileSync(configFile, 'utf8'));
      if (cfg.jarvisDir && fs.existsSync(path.join(cfg.jarvisDir, 'run.py'))) {
        console.log('[JARVIS Launcher] Found via config:', cfg.jarvisDir);
        return cfg.jarvisDir;
      }
    } catch {}
  }

  const candidates = [
    // 1. Portable .exe: Electron seta com a pasta onde o .exe está
    process.env.PORTABLE_EXECUTABLE_DIR,
    // 2. Pasta onde o executável está
    path.dirname(process.execPath),
    // 3. Source mode: launcher/ está dentro do JARVIS
    path.resolve(__dirname, '..'),
    // 4. CWD
    process.cwd(),
    // 5. Locais comuns de instalação
    path.join(HOME, 'Desktop', 'Jarvis'),
    path.join(HOME, 'OneDrive', 'Desktop', 'Jarvis'),
    path.join(HOME, 'OneDrive', 'Área de Trabalho', 'Jarvis'),
    path.join(HOME, 'OneDrive', 'Area de Trabalho', 'Jarvis'),
    'C:\\Jarvis',
    'C:\\Program Files\\Jarvis',
    // 6. Pasta do .exe (alternativa)
    process.env.PORTABLE_EXECUTABLE_FILE ? path.dirname(process.env.PORTABLE_EXECUTABLE_FILE) : null,
  ].filter(Boolean);

  for (const dir of candidates) {
    if (fs.existsSync(path.join(dir, 'run.py'))) {
      console.log('[JARVIS Launcher] Found JARVIS at:', dir);
      // Salvar no config pra próxima vez
      try {
        fs.writeFileSync(configFile, JSON.stringify({ jarvisDir: dir }, null, 2));
      } catch {}
      return dir;
    }
  }

  // Último fallback: subir diretórios até achar run.py
  let search = __dirname;
  for (let i = 0; i < 5; i++) {
    if (fs.existsSync(path.join(search, 'run.py'))) {
      console.log('[JARVIS Launcher] Found JARVIS (search) at:', search);
      return search;
    }
    search = path.dirname(search);
  }

  console.error('[JARVIS Launcher] Could not find run.py! Candidates:', candidates);
  return path.resolve(__dirname, '..');
}
const JARVIS_DIR = findJarvisDir();
const RUN_FILE = path.join(JARVIS_DIR, 'run.py');
const PYTHON_EXE = process.platform === 'win32'
  ? path.join(JARVIS_DIR, '.venv', 'Scripts', 'python.exe')
  : path.join(JARVIS_DIR, '.venv', 'bin', 'python');
const runtimeConfig = JSON.parse(execFileSync(
  PYTHON_EXE,
  ['-c', "import json; from app.core.config import HOST, PORT; print(json.dumps({'host': HOST, 'port': PORT}))"],
  { cwd: JARVIS_DIR, encoding: 'utf8', timeout: 5000, windowsHide: true }
));
const HOST = runtimeConfig.host;
const PORT = runtimeConfig.port;
const IS_WIN = process.platform === 'win32';
const IS_MAC = process.platform === 'darwin';
const IS_LINUX = process.platform === 'linux';

// Fix: eliminar erros de cache de GPU no Windows
app.commandLine.appendSwitch('disable-gpu');
app.commandLine.appendSwitch('disable-gpu-compositing');
app.commandLine.appendSwitch('disable-gpu-shader-disk-cache');
app.commandLine.appendSwitch('disable-software-rasterizer');
app.commandLine.appendSwitch('no-sandbox');
app.disableHardwareAcceleration();

let mainWindow = null;
let serverProcess = null;
let statusInterval = null;

// ── Janela principal ──
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 520,
    height: 740,
    resizable: false,
    frame: false,
    transparent: true,
    icon: path.join(__dirname, 'assets', 'icon.ico'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));
  mainWindow.on('closed', () => { mainWindow = null; });
}

// ── Health check ──
function checkServer() {
  return new Promise(resolve => {
    const req = http.get(`http://${HOST}:${PORT}/api/health`, { timeout: 3000 }, res => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => {
        try { resolve({ online: true, ...JSON.parse(data) }); }
        catch { resolve({ online: true }); }
      });
    });
    req.on('error', () => resolve({ online: false }));
    req.on('timeout', () => { req.destroy(); resolve({ online: false }); });
  });
}

// ── Verificar dependências ──
function checkDeps() {
  const result = { node: false, claude: false, env: false, nodeVersion: '', claudeVersion: '' };

  try {
    result.nodeVersion = execSync('node --version', { encoding: 'utf-8', timeout: 5000 }).trim();
    result.node = true;
  } catch {}

  try {
    result.claudeVersion = execSync('claude --version', { encoding: 'utf-8', timeout: 5000 }).trim();
    result.claude = true;
  } catch {}

  try {
    const envPath = path.join(JARVIS_DIR, '.env');
    if (fs.existsSync(envPath)) {
      const content = fs.readFileSync(envPath, 'utf-8');
      result.env = content.includes('OPENAI_API_KEY') && !content.includes('SUA_CHAVE_AQUI');
    }
  } catch {}

  return result;
}

// ── Iniciar servidor ──
function startServer() {
  if (serverProcess) return { success: false, reason: 'Servidor já está rodando' };

  try {
    if (!fs.existsSync(RUN_FILE)) {
      return { success: false, reason: `Backend Python nao encontrado: ${RUN_FILE}` };
    }
    if (!fs.existsSync(PYTHON_EXE)) {
      return { success: false, reason: `Ambiente Python nao encontrado: ${PYTHON_EXE}` };
    }

    serverProcess = spawn(PYTHON_EXE, [RUN_FILE], {
      cwd: JARVIS_DIR,
      env: { ...process.env, PATH: getFullPath() },
      stdio: ['ignore', 'pipe', 'pipe'],
      shell: false,
      detached: !IS_WIN
    });

    serverProcess.stdout.on('data', data => {
      const line = data.toString().trim();
      if (line && mainWindow) {
        mainWindow.webContents.send('server-log', line);
      }
    });

    serverProcess.stderr.on('data', data => {
      const line = data.toString().trim();
      if (line && mainWindow) {
        mainWindow.webContents.send('server-log', `[stderr] ${line}`);
      }
    });

    serverProcess.on('close', code => {
      serverProcess = null;
      if (mainWindow) {
        mainWindow.webContents.send('server-stopped', code);
      }
    });

    serverProcess.on('error', err => {
      serverProcess = null;
      if (mainWindow) {
        mainWindow.webContents.send('server-error', err.message);
      }
    });

    return { success: true, pid: serverProcess.pid };
  } catch (err) {
    return { success: false, reason: err.message };
  }
}

// ── Parar somente uma instancia validada pelo proprio FastAPI ──
function requestShutdown() {
  return new Promise(resolve => {
    const req = http.request({
      hostname: HOST,
      port: PORT,
      path: '/api/jarvis/shutdown',
      method: 'POST',
      timeout: 5000
    }, res => {
      res.resume();
      res.on('end', () => resolve(
        res.statusCode === 202
          ? { success: true }
          : { success: false, reason: `Shutdown recusado com HTTP ${res.statusCode}` }
      ));
    });
    req.on('error', error => resolve({ success: false, reason: error.message }));
    req.on('timeout', () => {
      req.destroy();
      resolve({ success: false, reason: 'Timeout ao solicitar shutdown do Jarvis Python' });
    });
    req.end();
  });
}

async function stopServer() {
  const status = await checkServer();
  if (!status.online) {
    serverProcess = null;
    return { success: true, alreadyStopped: true };
  }
  const result = await requestShutdown();
  if (result.success) serverProcess = null;
  return result;
}

// ── IPC Handlers ──
ipcMain.handle('check-deps', () => checkDeps());
ipcMain.handle('check-server', () => checkServer());

ipcMain.handle('start-server', async () => {
  const result = startServer();
  if (result.success) {
    // Aguarda servidor ficar online (max 15s)
    for (let i = 0; i < 30; i++) {
      await new Promise(r => setTimeout(r, 500));
      const status = await checkServer();
      if (status.online) return { success: true, status };
    }
    return { success: true, status: { online: false, message: 'Servidor iniciou mas não respondeu a tempo' } };
  }
  return result;
});

ipcMain.handle('stop-server', () => stopServer());

ipcMain.handle('restart-server', async () => {
  const stopped = await stopServer();
  if (!stopped.success) return stopped;
  await new Promise(r => setTimeout(r, 1500));
  const result = startServer();
  if (result.success) {
    for (let i = 0; i < 30; i++) {
      await new Promise(r => setTimeout(r, 500));
      const status = await checkServer();
      if (status.online) return { success: true, status };
    }
  }
  return result;
});

ipcMain.handle('open-browser', () => {
  shell.openExternal(`http://${HOST}:${PORT}`);
  return { success: true };
});

ipcMain.handle('open-terminal-claude', () => {
  if (IS_WIN) {
    spawn('cmd', ['/c', 'start', 'cmd', '/k', 'claude auth login --claudeai'], { cwd: JARVIS_DIR, detached: true, shell: true });
  } else if (IS_MAC) {
    spawn('osascript', ['-e', `tell app "Terminal" to do script "cd '${JARVIS_DIR}' && claude auth login --claudeai"`], { detached: true });
  } else {
    // Linux: tenta varios terminais
    const term = ['gnome-terminal', 'konsole', 'xterm', 'x-terminal-emulator'].find(t => {
      try { execSync(`which ${t}`, { stdio: 'pipe' }); return true; } catch { return false; }
    }) || 'xterm';
    spawn(term, ['--', 'bash', '-c', `cd "${JARVIS_DIR}" && claude login; exec bash`], { detached: true });
  }
  return { success: true };
});

ipcMain.handle('open-claude-terminal', () => {
  if (IS_WIN) {
    spawn('cmd', ['/c', 'start', 'cmd', '/k', `cd /d "${JARVIS_DIR}" && echo. && echo   JARVIS - Claude Terminal && echo. && claude`], {
      cwd: JARVIS_DIR, detached: true, shell: true
    });
  } else if (IS_MAC) {
    spawn('osascript', ['-e', `tell app "Terminal" to do script "cd '${JARVIS_DIR}' && echo 'JARVIS - Claude Terminal' && claude"`], { detached: true });
  } else {
    const term = ['gnome-terminal', 'konsole', 'xterm'].find(t => {
      try { execSync(`which ${t}`, { stdio: 'pipe' }); return true; } catch { return false; }
    }) || 'xterm';
    spawn(term, ['--', 'bash', '-c', `cd "${JARVIS_DIR}" && echo "JARVIS - Claude Terminal" && claude; exec bash`], { detached: true });
  }
  return { success: true };
});

ipcMain.handle('window-minimize', () => { mainWindow?.minimize(); });
ipcMain.handle('window-close', () => { mainWindow?.close(); });

// ── Auto-fix via Claude CLI (roda direto do launcher, sem servidor) ──
ipcMain.handle('autofix', async (_, issues) => {
  if (!issues || issues.length === 0) return { success: false, reason: 'Nenhum problema informado' };

  // Verificar se Claude CLI existe
  let hasClaude = false;
  try {
    execSync('claude --version', { stdio: 'pipe', timeout: 5000, shell: true });
    hasClaude = true;
  } catch {}

  if (!hasClaude) {
    // Tentar instalar o Claude CLI primeiro
    mainWindow?.webContents.send('autofix-log', '[JARVIS] Claude CLI nao encontrado. Tentando instalar...\n');
    try {
      const installCmd = IS_WIN
        ? 'npm install -g @anthropic-ai/claude-code'
        : 'npm install -g @anthropic-ai/claude-code';
      const result = execSync(installCmd, { encoding: 'utf-8', timeout: 120000, shell: true });
      mainWindow?.webContents.send('autofix-log', result + '\n');
      mainWindow?.webContents.send('autofix-log', '[JARVIS] Claude CLI instalado. Voce precisa autenticar: claude login\n');

      // Abrir terminal pra login
      if (IS_WIN) {
        spawn('cmd', ['/c', 'start', 'cmd', '/k', 'claude login'], { cwd: JARVIS_DIR, detached: true, shell: true });
      } else if (IS_MAC) {
        spawn('osascript', ['-e', `tell app "Terminal" to do script "claude login"`], { detached: true });
      }
      mainWindow?.webContents.send('autofix-log', '[autofix-done] Claude CLI instalado. Faca login e tente novamente.\n');
      return { success: true, needsLogin: true };
    } catch (e) {
      mainWindow?.webContents.send('autofix-log', `[ERRO] Falha ao instalar Claude CLI: ${e.message}\n`);
      mainWindow?.webContents.send('autofix-log', '[autofix-done] Instale manualmente: npm install -g @anthropic-ai/claude-code\n');
      return { success: false, reason: e.message };
    }
  }

  // Claude CLI disponivel — montar prompt de diagnostico
  const diagLines = issues.map(i => `- ${i.key}: ${i.detail}`).join('\n');

  const fixPrompt = `You are JARVIS system repair agent. Fix these issues in the JARVIS installation at "${JARVIS_DIR}":

${diagLines}

CONTEXT:
- JARVIS runs on Python + FastAPI (run.py) at ${HOST}:${PORT}
- Voice uses OpenAI Realtime API (needs OPENAI_API_KEY in .env)
- Task execution uses Claude CLI
- .env should be at: ${path.join(JARVIS_DIR, '.env')}
- package.json is at: ${path.join(JARVIS_DIR, 'package.json')}
- OS: ${IS_WIN ? 'Windows' : IS_MAC ? 'macOS' : 'Linux'}

FIX EACH ISSUE:
1. Missing .env or no OPENAI_API_KEY → Create .env with OPENAI_API_KEY=YOUR_KEY_HERE and tell user to replace
2. Python environment missing → Recreate .venv and install the approved dependencies
3. Claude not authenticated → Tell user to run: claude login
4. Port conflict → Kill process on port ${PORT}
5. Missing dependencies → Install them
6. Permission errors → Fix permissions

DO NOT ask questions. Fix what you can. Report what needs user action.`;

  // Spawnar Claude e streamer output
  return new Promise((resolve) => {
    const proc = spawn('claude', [
      '--print', '--output-format', 'text',
      '--model', 'claude-sonnet-4-6',
      '--dangerously-skip-permissions',
      '-p', fixPrompt
    ], {
      cwd: JARVIS_DIR,
      env: process.env,
      shell: true
    });

    let output = '';

    proc.stdout.on('data', (data) => {
      const chunk = data.toString();
      output += chunk;
      mainWindow?.webContents.send('autofix-log', chunk);
    });

    proc.stderr.on('data', (data) => {
      const msg = data.toString().trim();
      if (msg && !msg.includes('ExperimentalWarning')) {
        mainWindow?.webContents.send('autofix-log', `[stderr] ${msg}\n`);
      }
    });

    proc.on('close', (code) => {
      mainWindow?.webContents.send('autofix-log', `\n[autofix-done] Concluido (codigo ${code})\n`);
      resolve({ success: code === 0, output: output.slice(-500) });
    });

    proc.on('error', (err) => {
      mainWindow?.webContents.send('autofix-log', `[autofix-error] ${err.message}\n`);
      resolve({ success: false, reason: err.message });
    });

    // Timeout de 2 minutos
    setTimeout(() => {
      try { proc.kill(); } catch {}
      mainWindow?.webContents.send('autofix-log', '\n[autofix-timeout] Tempo limite atingido.\n');
      resolve({ success: false, reason: 'timeout' });
    }, 120000);
  });
});

// ── Auto-install de dependencias basicas ──
ipcMain.handle('auto-install-deps', async () => {
  const results = [];

  // 1. Verificar node_modules
  const nodeModulesPath = path.join(JARVIS_DIR, 'node_modules');
  if (!fs.existsSync(nodeModulesPath)) {
    mainWindow?.webContents.send('autofix-log', '[JARVIS] node_modules nao encontrado. Instalando dependencias...\n');
    try {
      const out = execSync('npm install', { cwd: JARVIS_DIR, encoding: 'utf-8', timeout: 120000, shell: true });
      mainWindow?.webContents.send('autofix-log', out + '\n');
      results.push({ key: 'node_modules', status: 'ok' });
    } catch (e) {
      mainWindow?.webContents.send('autofix-log', `[ERRO] npm install falhou: ${e.message}\n`);
      results.push({ key: 'node_modules', status: 'error', detail: e.message });
    }
  } else {
    results.push({ key: 'node_modules', status: 'ok' });
  }

  // 2. Verificar .env
  const envPath = path.join(JARVIS_DIR, '.env');
  if (!fs.existsSync(envPath)) {
    mainWindow?.webContents.send('autofix-log', '[JARVIS] .env nao encontrado. Criando template...\n');
    const template = `# JARVIS Configuration
# Substitua YOUR_KEY_HERE pela sua chave da OpenAI
OPENAI_API_KEY=YOUR_KEY_HERE
`;
    fs.writeFileSync(envPath, template);
    mainWindow?.webContents.send('autofix-log', '[JARVIS] .env criado. IMPORTANTE: Edite e coloque sua OPENAI_API_KEY.\n');
    results.push({ key: '.env', status: 'created' });
  } else {
    results.push({ key: '.env', status: 'ok' });
  }

  // 3. Verificar Claude CLI
  try {
    execSync('claude --version', { stdio: 'pipe', timeout: 5000, shell: true });
    results.push({ key: 'claude-cli', status: 'ok' });
  } catch {
    mainWindow?.webContents.send('autofix-log', '[JARVIS] Claude CLI nao encontrado. Instalando...\n');
    try {
      execSync('npm install -g @anthropic-ai/claude-code', { encoding: 'utf-8', timeout: 120000, shell: true });
      mainWindow?.webContents.send('autofix-log', '[JARVIS] Claude CLI instalado. Execute "claude login" para autenticar.\n');
      results.push({ key: 'claude-cli', status: 'installed' });
    } catch (e) {
      mainWindow?.webContents.send('autofix-log', `[ERRO] Instalacao Claude CLI falhou: ${e.message}\n`);
      results.push({ key: 'claude-cli', status: 'error', detail: e.message });
    }
  }

  return results;
});

ipcMain.handle('get-system-info', () => ({
  platform: process.platform,
  arch: process.arch,
  osName: IS_WIN ? 'Windows' : IS_MAC ? 'macOS' : 'Linux',
  osVersion: os.release(),
  hostname: os.hostname(),
  jarvisDir: JARVIS_DIR,
  port: PORT
}));

// ── Auto-Update (silencioso, executado ao abrir) ──
async function runAutoUpdate() {
  try {
    const check = await updater.checkForUpdate(JARVIS_DIR);

    if (check.error) {
      console.log('[Updater]', check.error);
      if (mainWindow) {
        mainWindow.webContents.send('update-status', { state: 'offline' });
      }
      return;
    }

    if (!check.hasUpdate) {
      console.log(`[Updater] Já está atualizado (${check.localVersion})`);
      if (mainWindow) {
        mainWindow.webContents.send('update-status', {
          state: 'current',
          version: check.localVersion
        });
      }
      return;
    }

    console.log(`[Updater] Atualizando ${check.localVersion} → ${check.remoteVersion}`);
    if (mainWindow) {
      mainWindow.webContents.send('update-status', {
        state: 'updating',
        from: check.localVersion,
        to: check.remoteVersion
      });
    }

    const result = await updater.applyUpdate(JARVIS_DIR, (msg) => {
      if (mainWindow) {
        mainWindow.webContents.send('update-status', { state: 'updating', msg });
      }
    });

    if (result.success) {
      console.log(`[Updater] Atualizado! ${result.updatedCount} arquivos`);
      if (mainWindow) {
        mainWindow.webContents.send('update-status', {
          state: 'done',
          version: check.remoteVersion,
          files: result.updatedCount
        });
      }
    } else {
      console.error('[Updater] Falhou:', result.error);
      if (mainWindow) {
        mainWindow.webContents.send('update-status', {
          state: 'error',
          error: result.error
        });
      }
    }
  } catch (err) {
    console.error('[Updater] Exception:', err);
  }
}

// ── App lifecycle ──
app.whenReady().then(async () => {
  createWindow();
  // Roda auto-update 1.5s após abrir (pra dar tempo do UI carregar)
  setTimeout(runAutoUpdate, 1500);
});

app.on('window-all-closed', () => {
  // NÃO mata o servidor ao fechar o launcher
  if (statusInterval) clearInterval(statusInterval);
  app.quit();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});

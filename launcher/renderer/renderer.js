// ── Elementos ──
const reactor = document.getElementById('reactor');
const statusServer = document.getElementById('status-server');
const statusNode = document.getElementById('status-node');
const statusClaude = document.getElementById('status-claude');
const statusEnv = document.getElementById('status-env');
const btnStart = document.getElementById('btn-start');
const btnStop = document.getElementById('btn-stop');
const btnRestart = document.getElementById('btn-restart');
const btnBrowser = document.getElementById('btn-browser');
const btnClaudeSetup = document.getElementById('btn-claude-setup');
const logContent = document.getElementById('log-content');

let isOnline = false;

// ── Utilitários ──
function addLog(msg, type = '') {
  const div = document.createElement('div');
  div.className = `log-line ${type}`;
  div.textContent = msg;
  logContent.appendChild(div);
  logContent.scrollTop = logContent.scrollHeight;
  // Limita a 200 linhas
  while (logContent.children.length > 200) logContent.removeChild(logContent.firstChild);
}

function setServerStatus(online) {
  isOnline = online;
  if (online) {
    statusServer.innerHTML = '<span class="dot dot-on"></span> Online';
    reactor.className = 'reactor online';
    btnStart.disabled = true;
    btnStop.disabled = false;
    btnRestart.disabled = false;
    btnBrowser.disabled = false;
  } else {
    statusServer.innerHTML = '<span class="dot dot-off"></span> Offline';
    reactor.className = 'reactor';
    btnStart.disabled = false;
    btnStop.disabled = true;
    btnRestart.disabled = true;
    btnBrowser.disabled = true;
  }
}

function setLoading(loading) {
  if (loading) {
    reactor.className = 'reactor loading';
    btnStart.disabled = true;
    btnStop.disabled = true;
    btnRestart.disabled = true;
    btnStart.classList.add('loading');
  } else {
    btnStart.classList.remove('loading');
  }
}

// ── Verificar dependencias ──
let detectedIssues = [];

async function checkDeps() {
  addLog('Verificando dependencias...', 'info');
  detectedIssues = [];
  const deps = await jarvis.checkDeps();

  // Node.js
  if (deps.node) {
    statusNode.innerHTML = `<span class="status-ok">${deps.nodeVersion}</span>`;
    addLog(`Node.js: ${deps.nodeVersion}`, 'success');
  } else {
    statusNode.innerHTML = '<span class="status-err">Nao encontrado</span>';
    addLog('Node.js nao encontrado no PATH', 'error');
    detectedIssues.push({ key: 'node', detail: 'Node.js not found in PATH' });
  }

  // Claude CLI
  if (deps.claude) {
    statusClaude.innerHTML = '<span class="status-ok">Instalado</span>';
    addLog('Claude CLI: OK', 'success');
    btnClaudeSetup.style.display = 'none';
  } else {
    statusClaude.innerHTML = '<span class="status-err">Nao instalado</span>';
    addLog('Claude CLI nao encontrado', 'error');
    btnClaudeSetup.style.display = 'block';
    detectedIssues.push({ key: 'claude_cli', detail: 'Claude CLI not installed or not in PATH' });
  }

  // .env
  if (deps.env) {
    statusEnv.innerHTML = '<span class="status-ok">Configurada</span>';
    addLog('OpenAI API Key: OK', 'success');
  } else {
    statusEnv.innerHTML = '<span class="status-warn">Nao configurada</span>';
    addLog('.env sem OPENAI_API_KEY', 'error');
    detectedIssues.push({ key: 'openai_env', detail: '.env missing or no OPENAI_API_KEY configured' });
  }

  // Mostrar/ocultar botao de auto-fix
  const btnFix = document.getElementById('btn-autofix');
  if (btnFix) {
    btnFix.style.display = detectedIssues.length > 0 ? 'block' : 'none';
  }

  return deps;
}

// ── Verificar se servidor ja esta rodando ──
async function checkExistingServer() {
  const status = await jarvis.checkServer();
  if (status.online) {
    setServerStatus(true);
      addLog('Servidor ja estava rodando', 'success');
  }
  return status.online;
}

// ── Handlers dos botoes ──
async function handleStart() {
  setLoading(true);
  addLog('Iniciando servidor FELIPE...', 'info');

  const result = await jarvis.startServer();

  if (result.success && result.status?.online) {
    setServerStatus(true);
    addLog('Servidor online! Abrindo navegador...', 'success');
    // Aguarda 1s e abre o browser
    setTimeout(() => jarvis.openBrowser(), 1000);
  } else {
    setLoading(false);
    setServerStatus(false);
    addLog(`Falha ao iniciar: ${result.reason || 'Servidor nao respondeu a tempo'}`, 'error');
  }
}

async function handleStop() {
  addLog('Desligando servidor...', 'info');
  const result = await jarvis.stopServer();
  if (result.success) {
    setServerStatus(false);
    addLog(result.orphan ? 'Processo orfao encerrado' : 'Servidor desligado', 'success');
  } else {
    addLog('Erro ao desligar servidor', 'error');
  }
}

async function handleRestart() {
  setLoading(true);
  addLog('Reiniciando servidor...', 'info');

  const result = await jarvis.restartServer();

  if (result.success && result.status?.online) {
    setServerStatus(true);
    addLog('Servidor reiniciado com sucesso!', 'success');
  } else {
    setLoading(false);
    setServerStatus(false);
    addLog('Falha ao reiniciar', 'error');
  }
}

function handleBrowser() {
  jarvis.openBrowser();
  addLog('Abrindo FELIPE no navegador...', 'info');
}

// ── Listeners de log do servidor ──
jarvis.onLog(msg => {
  const isErr = msg.includes('[stderr]') || msg.includes('Error') || msg.includes('error');
  const isOk = msg.includes('listening') || msg.includes('Server') || msg.includes('Connected');
  addLog(msg, isErr ? 'error' : isOk ? 'success' : '');
});

jarvis.onStopped(code => {
  setServerStatus(false);
  addLog(`Servidor encerrou (codigo ${code})`, code === 0 ? '' : 'error');
});

jarvis.onError(msg => {
  setServerStatus(false);
  addLog(`Erro: ${msg}`, 'error');
});

// ── Polling de status (a cada 5s) ──
setInterval(async () => {
  const status = await jarvis.checkServer();
  if (status.online !== isOnline) {
    setServerStatus(status.online);
    if (status.online) addLog('Servidor detectado online', 'success');
    else addLog('Servidor ficou offline', 'error');
  }
}, 5000);

// ── Init ──
(async () => {
  addLog('FELIPE Launcher v1.0', 'info');
  addLog('Powered by Gabriel Felipe Fernandes', '');

  // Detectar OS
  try {
    const sys = await jarvis.getSystemInfo();
    addLog(`Sistema: ${sys.osName} ${sys.osVersion} (${sys.arch})`, 'info');
    addLog(`Diretorio: ${sys.jarvisDir}`, '');
    addLog(`Porta: ${sys.port}`, '');
  } catch {}

  addLog('─'.repeat(40), '');

  await checkDeps();
  await checkExistingServer();
})();

// ── Auto-fix via Claude CLI ──
async function handleAutofix() {
  const btnFix = document.getElementById('btn-autofix');
  if (btnFix) {
    btnFix.disabled = true;
    btnFix.textContent = 'Corrigindo...';
  }

  addLog('', '');
  addLog('═'.repeat(40), 'info');
  addLog('FELIPE AUTO-FIX — Correcao automatica', 'info');
  addLog('═'.repeat(40), 'info');
  addLog('', '');

  if (detectedIssues.length === 0) {
    addLog('Nenhum problema detectado.', 'success');
    if (btnFix) { btnFix.disabled = false; btnFix.textContent = 'Corrigir Automaticamente'; }
    return;
  }

  // Primeiro tenta instalar deps basicas (sem Claude)
  addLog('Fase 1: Instalando dependencias basicas...', 'info');
  try {
    const depsResult = await jarvis.autoInstallDeps();
    for (const r of depsResult) {
      if (r.status === 'ok') addLog(`  ${r.key}: OK`, 'success');
      else if (r.status === 'created') addLog(`  ${r.key}: Criado (precisa configurar)`, 'success');
      else if (r.status === 'installed') addLog(`  ${r.key}: Instalado (precisa autenticar)`, 'success');
      else addLog(`  ${r.key}: ERRO — ${r.detail}`, 'error');
    }
  } catch (e) {
    addLog(`Erro na fase 1: ${e.message}`, 'error');
  }

  // Se Claude CLI esta disponivel, usar pra fix avancado
  const depsAfter = await jarvis.checkDeps();
  if (depsAfter.claude) {
    addLog('', '');
    addLog('Fase 2: Claude analisando e corrigindo...', 'info');
    addLog('', '');

    try {
      await jarvis.autofix(detectedIssues);
      // Output vem via onAutofixLog
    } catch (e) {
      addLog(`Erro na fase 2: ${e.message}`, 'error');
    }
  } else {
    addLog('', '');
    addLog('Claude CLI nao disponivel para fase 2.', 'error');
    addLog('Execute: npm install -g @anthropic-ai/claude-code', '');
    addLog('Depois: claude login', '');
  }

  // Re-verificar apos fix
  addLog('', '');
  addLog('Re-verificando sistemas...', 'info');
  await checkDeps();
  await checkExistingServer();

  if (btnFix) {
    btnFix.disabled = false;
    btnFix.textContent = 'Corrigir Automaticamente';
  }
}

// Listener de log do auto-fix (via IPC)
jarvis.onAutofixLog(msg => {
  if (msg.includes('[autofix-done]') || msg.includes('[autofix-error]') || msg.includes('[autofix-timeout]')) {
    addLog(msg.replace(/\[autofix-\w+\]\s*/, ''), msg.includes('error') || msg.includes('timeout') ? 'error' : 'success');
  } else {
    // Dividir em linhas pra exibir limpo
    msg.split('\n').forEach(line => {
      if (line.trim()) addLog(line, line.includes('[stderr]') ? 'error' : '');
    });
  }
});

// Expor funcoes globais para onclick
window.handleStart = handleStart;
window.handleAutofix = handleAutofix;
window.handleStop = handleStop;
window.handleRestart = handleRestart;
window.handleBrowser = handleBrowser;


// === AUTO-UPDATE UI ===
const updateCard = document.getElementById('update-card');
const updateHeader = document.getElementById('update-header');
const updateMsg = document.getElementById('update-msg');
const updateProgressFill = document.getElementById('update-progress-fill');

let updateProgressTimer = null;

function showUpdateCard() {
  updateCard.style.display = 'block';
  updateCard.className = 'update-card';
}

function setProgress(percent) {
  updateProgressFill.style.width = percent + '%';
}

function animateProgress(target, duration = 1000) {
  const start = parseFloat(updateProgressFill.style.width) || 0;
  const startTime = Date.now();
  if (updateProgressTimer) clearInterval(updateProgressTimer);
  updateProgressTimer = setInterval(() => {
    const elapsed = Date.now() - startTime;
    const t = Math.min(1, elapsed / duration);
    const current = start + (target - start) * t;
    setProgress(current);
    if (t >= 1) clearInterval(updateProgressTimer);
  }, 16);
}

jarvis.onUpdateStatus((data) => {
  if (!data) return;

  if (data.state === 'offline') {
    // Sem internet ou token invalido — esconde silenciosamente
    updateCard.style.display = 'none';
    return;
  }

  if (data.state === 'current') {
    showUpdateCard();
    updateCard.classList.add('current');
    updateHeader.textContent = 'FELIPE atualizado';
    updateMsg.textContent = 'Versao ' + (data.version || '?') + ' — tudo em dia';
    setProgress(100);
    // Esconde apos 4 segundos
    setTimeout(() => { updateCard.style.display = 'none'; }, 4000);
    return;
  }

  if (data.state === 'updating') {
    showUpdateCard();
    if (data.from && data.to) {
      updateHeader.textContent = 'Atualizando FELIPE';
      updateMsg.textContent = data.from + '  →  ' + data.to;
      animateProgress(50, 2000);
    } else if (data.msg) {
      updateMsg.textContent = data.msg;
      if (data.msg.includes('Baixando')) animateProgress(40, 1500);
      else if (data.msg.includes('Aplicando')) animateProgress(85, 1000);
      else if (data.msg.includes('Concluído')) animateProgress(100, 400);
    }
    return;
  }

  if (data.state === 'done') {
    updateCard.classList.add('success');
    updateHeader.textContent = 'Atualizacao concluida';
    updateMsg.textContent = 'Versao ' + data.version + ' — ' + data.files + ' arquivos atualizados';
    setProgress(100);
    // Esconde apos 5 segundos
    setTimeout(() => { updateCard.style.display = 'none'; }, 5000);
    return;
  }

  if (data.state === 'error') {
    updateCard.classList.add('error');
    updateHeader.textContent = 'Erro na atualizacao';
    updateMsg.textContent = data.error || 'Falha desconhecida';
    setProgress(100);
    setTimeout(() => { updateCard.style.display = 'none'; }, 6000);
    return;
  }
});

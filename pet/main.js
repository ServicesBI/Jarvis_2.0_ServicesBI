const { app, BrowserWindow, ipcMain, Menu, shell, screen } = require('electron');
const path = require('path');
const http = require('http');
const fs = require('fs');

let mainWindow = null;
let dragOffset = null;

// Single instance lock
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) { mainWindow.show(); mainWindow.focus(); }
  });
}

function fetchJSON(url) {
  return new Promise((resolve) => {
    const req = http.get(url, { timeout: 3000 }, (res) => {
      let data = '';
      res.on('data', (chunk) => (data += chunk));
      res.on('end', () => {
        try { resolve(JSON.parse(data)); } catch { resolve({ status: 'online' }); }
      });
    });
    req.on('error', () => resolve(null));
    req.on('timeout', () => { req.destroy(); resolve(null); });
  });
}

function postJSON(url, payload = {}) {
  return new Promise((resolve) => {
    const body = JSON.stringify(payload);
    const target = new URL(url);
    const req = http.request({
      hostname: target.hostname,
      port: target.port,
      path: target.pathname,
      method: 'POST',
      timeout: 3000,
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) },
    }, (res) => {
      let data = '';
      res.on('data', (chunk) => (data += chunk));
      res.on('end', () => {
        try { resolve(JSON.parse(data)); } catch { resolve({ ok: res.statusCode < 400 }); }
      });
    });
    req.on('error', () => resolve(null));
    req.on('timeout', () => { req.destroy(); resolve(null); });
    req.end(body);
  });
}

function createWindow() {
  const { width, height } = screen.getPrimaryDisplay().workAreaSize;

  mainWindow = new BrowserWindow({
    width: 200, height: 200,
    x: width - 220, y: height - 220,
    frame: false, transparent: true,
    alwaysOnTop: true, skipTaskbar: true,
    resizable: false, hasShadow: false,
    backgroundColor: '#00000000',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
    },
  });

  mainWindow.loadFile('pet.html');
  mainWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  mainWindow.on('closed', () => { mainWindow = null; });
}

// Preload
const preloadContent = `
const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('jarvis', {
  getStatus: () => ipcRenderer.invoke('get-jarvis-status'),
  openCockpit: () => ipcRenderer.invoke('open-cockpit'),
  moveToCenter: () => ipcRenderer.invoke('move-to-center'),
  closePet: () => ipcRenderer.invoke('close-pet'),
  setMicActive: (active) => ipcRenderer.invoke('set-mic-active', Boolean(active)),
  startDrag: (screenX, screenY) => ipcRenderer.send('drag-start', screenX, screenY),
  onDrag: (screenX, screenY) => ipcRenderer.send('drag-move', screenX, screenY),
  stopDrag: () => ipcRenderer.send('drag-stop'),
  showMenu: () => ipcRenderer.send('show-context-menu'),
});
`;
fs.writeFileSync(path.join(__dirname, 'preload.js'), preloadContent, 'utf-8');

// === IPC ===
ipcMain.handle('get-jarvis-status', async () => {
  const result = await fetchJSON('http://127.0.0.1:8000/api/health');
  return result ? { online: true, ...result } : { online: false };
});

ipcMain.handle('open-cockpit', () => {
  shell.openExternal('http://127.0.0.1:8000');
  return true;
});

ipcMain.handle('set-mic-active', async (_event, active) => {
  const base = 'http://127.0.0.1:8000';
  const cowork = await postJSON(`${base}/api/cowork/${active ? 'start' : 'stop'}`);
  const mic = await postJSON(`${base}/api/pet/mic-state`, { active });
  return { ok: Boolean(cowork && mic), active };
});

ipcMain.handle('move-to-center', () => {
  if (!mainWindow) return;
  const { width, height } = screen.getPrimaryDisplay().workAreaSize;
  mainWindow.setPosition(Math.round(width / 2 - 100), Math.round(height / 2 - 100));
});

ipcMain.handle('close-pet', () => { app.quit(); });

// Drag via IPC (no app-region needed)
ipcMain.on('drag-start', (e, screenX, screenY) => {
  if (!mainWindow) return;
  const [winX, winY] = mainWindow.getPosition();
  dragOffset = { x: screenX - winX, y: screenY - winY };
});

ipcMain.on('drag-move', (e, screenX, screenY) => {
  if (!mainWindow || !dragOffset) return;
  mainWindow.setPosition(screenX - dragOffset.x, screenY - dragOffset.y);
});

ipcMain.on('drag-stop', () => { dragOffset = null; });

// Context menu via IPC
ipcMain.on('show-context-menu', () => {
  if (!mainWindow) return;
  const menu = Menu.buildFromTemplate([
    { label: 'Abrir Cockpit', click: () => shell.openExternal('http://127.0.0.1:8000') },
    {
      label: 'Mover pro Centro',
      click: () => {
        const { width, height } = screen.getPrimaryDisplay().workAreaSize;
        mainWindow.setPosition(Math.round(width / 2 - 100), Math.round(height / 2 - 100));
      }
    },
    { type: 'separator' },
    { label: 'Fechar', click: () => app.quit() }
  ]);
  menu.popup({ window: mainWindow });
});

app.whenReady().then(createWindow);
app.on('window-all-closed', () => app.quit());

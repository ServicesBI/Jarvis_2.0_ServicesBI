const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('jarvis', {
  checkDeps:      () => ipcRenderer.invoke('check-deps'),
  checkServer:    () => ipcRenderer.invoke('check-server'),
  startServer:    () => ipcRenderer.invoke('start-server'),
  stopServer:     () => ipcRenderer.invoke('stop-server'),
  restartServer:  () => ipcRenderer.invoke('restart-server'),
  openBrowser:    () => ipcRenderer.invoke('open-browser'),
  openClaudeLogin:() => ipcRenderer.invoke('open-terminal-claude'),
  openClaudeTerminal:() => ipcRenderer.invoke('open-claude-terminal'),
  getSystemInfo: () => ipcRenderer.invoke('get-system-info'),
  autofix: (issues) => ipcRenderer.invoke('autofix', issues),
  autoInstallDeps: () => ipcRenderer.invoke('auto-install-deps'),
  onAutofixLog: (cb) => ipcRenderer.on('autofix-log', (_, msg) => cb(msg)),
  minimize:       () => ipcRenderer.invoke('window-minimize'),
  close:          () => ipcRenderer.invoke('window-close'),
  onLog:          (cb) => ipcRenderer.on('server-log', (_, msg) => cb(msg)),
  onStopped:      (cb) => ipcRenderer.on('server-stopped', (_, code) => cb(code)),
  onError:        (cb) => ipcRenderer.on('server-error', (_, msg) => cb(msg)),
  onUpdateStatus: (cb) => ipcRenderer.on('update-status', (_, data) => cb(data)),
});


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

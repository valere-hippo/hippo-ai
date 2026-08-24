const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electron', {
  selectFolder: () => ipcRenderer.invoke('select-folder'),
  logError: (msg) => ipcRenderer.send('renderer-log', msg),
  saveFile: (args) => ipcRenderer.invoke('save-file', args),
})

const { contextBridge, ipcRenderer } = require('electron')

// Notify main process that preload executed
try{ ipcRenderer.send('renderer-log', 'preload loaded') }catch(e){ }

contextBridge.exposeInMainWorld('electron', {
  selectFolder: () => ipcRenderer.invoke('select-folder'),
  logError: (msg) => ipcRenderer.send('renderer-log', msg),
  saveFile: (args) => ipcRenderer.invoke('save-file', args),
})

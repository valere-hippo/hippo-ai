const { contextBridge, ipcRenderer } = require('electron')

// Notify main process that preload executed
try{ ipcRenderer.send('renderer-log', 'preload loaded') }catch(e){ }

let runtimeConfig = {}
try {
  runtimeConfig = ipcRenderer.sendSync('get-runtime-config') || {}
} catch (error) {
  runtimeConfig = {}
}

contextBridge.exposeInMainWorld('electron', {
  selectFolder: () => ipcRenderer.invoke('select-folder'),
  logError: (msg) => ipcRenderer.send('renderer-log', msg),
  saveFile: (args) => ipcRenderer.invoke('save-file', args),
  ocrImage: (args) => ipcRenderer.invoke('ocr-image', args),
  runtimeConfig,
})

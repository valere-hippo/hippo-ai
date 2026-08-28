const { app, BrowserWindow, Menu, ipcMain, dialog } = require('electron')
const path = require('path')
const fs = require('fs')
const Tesseract = require('tesseract.js')

function loadRuntimeConfig() {
  const defaultApiUrl = process.env.HIPPO_API_URL || 'http://localhost:8000'
  const configPath = path.join(__dirname, 'build-config.json')

  try {
    if (fs.existsSync(configPath)) {
      const parsed = JSON.parse(fs.readFileSync(configPath, 'utf8'))
      const apiUrl = String(parsed?.apiUrl || '').trim()
      return {
        apiUrl: apiUrl || defaultApiUrl,
      }
    }
  } catch (error) {
    console.warn('Failed to load runtime config', error)
  }

  return { apiUrl: defaultApiUrl }
}

const runtimeConfig = loadRuntimeConfig()

function configurePermissions() {
  try {
    const permissions = new Set(['media', 'microphone', 'display-capture'])
    const handler = (webContents, permission, callback) => {
      if (permissions.has(permission)) {
        callback(true)
        return
      }
      callback(false)
    }

    if (app?.whenReady) {
      const session = app ? require('electron').session : null
      if (session?.defaultSession?.setPermissionRequestHandler) {
        session.defaultSession.setPermissionRequestHandler(handler)
      }
      if (session?.defaultSession?.setPermissionCheckHandler) {
        session.defaultSession.setPermissionCheckHandler((webContents, permission) => permissions.has(permission))
      }
    }
  } catch (error) {
    console.warn('Permission configuration failed', error)
  }
}

function createWindow () {
  const win = new BrowserWindow({
    width: 1440,
    height: 960,
    minWidth: 1180,
    minHeight: 760,
    backgroundColor: '#0a1016',
    autoHideMenuBar: true,
    icon: path.join(__dirname, 'renderer', 'assets', 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
    }
  })

  Menu.setApplicationMenu(null)
  win.removeMenu()
  win.setMenuBarVisibility(false)
  win.loadFile(path.join(__dirname, 'renderer/index.html'))
}

app.whenReady().then(() => {
  configurePermissions()
  createWindow()
  app.on('activate', function () {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', function () {
  if (process.platform !== 'darwin') app.quit()
})

ipcMain.on('get-runtime-config', (event) => {
  event.returnValue = runtimeConfig
})

ipcMain.handle('select-folder', async () => {
  const result = await dialog.showOpenDialog({ properties: ['openDirectory'] })
  if (result.canceled) return null
  return result.filePaths[0]
})

ipcMain.handle('save-file', async (event, { folder, filename, data }) => {
  try{
    if(!fs.existsSync(folder)) fs.mkdirSync(folder, { recursive: true })
    const filePath = path.join(folder, filename)
    if (typeof data === 'object' && data !== null && data.base64) {
      fs.writeFileSync(filePath, Buffer.from(data.base64, 'base64'))
    } else if (typeof data === 'object' && data !== null && data.bytes) {
      fs.writeFileSync(filePath, Buffer.from(data.bytes))
    } else if (typeof data === 'string' && data.startsWith('base64:')) {
      fs.writeFileSync(filePath, Buffer.from(data.slice(7), 'base64'))
    } else {
      fs.writeFileSync(filePath, data, 'utf8')
    }
    return { ok: true, path: filePath }
  }catch(e){ return { ok: false, error: e.message } }
})

ipcMain.handle('ocr-image', async (event, { dataUrl }) => {
  try {
    if (!dataUrl) return { ok: false, error: 'No image data provided' }
    const result = await Tesseract.recognize(dataUrl, 'deu+eng')
    const text = (result?.data?.text || '').trim()
    return { ok: true, text }
  } catch (e) {
    return { ok: false, error: e.message }
  }
})

// collect renderer console errors
const logPath = path.join(__dirname, '.logs')
try { fs.mkdirSync(logPath, { recursive: true }) } catch (e) {}
const logFile = path.join(logPath, 'renderer.log')
ipcMain.on('renderer-log', (event, msg) => {
  try { fs.appendFileSync(logFile, `[${new Date().toISOString()}] ${msg}\n`) } catch (e) {}
})

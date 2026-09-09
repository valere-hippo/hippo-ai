const { app, BrowserWindow, Menu, ipcMain, dialog, clipboard } = require('electron')
const { spawn, spawnSync } = require('child_process')
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

ipcMain.handle('copy-to-clipboard', async (event, text) => {
  try {
    clipboard.writeText(String(text || ''))
    return { ok: true }
  } catch (error) {
    return { ok: false, error: error.message }
  }
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

function hasXdotool() {
  if (process.platform !== 'linux') return false
  const result = spawnSync('bash', ['-lc', 'command -v xdotool'], { encoding: 'utf8' })
  return result.status === 0 && Boolean(String(result.stdout || '').trim())
}

function spawnDetached(command, args = [], options = {}) {
  const child = spawn(command, args, {
    detached: true,
    stdio: 'ignore',
    shell: false,
    ...options,
  })
  child.unref()
  return child.pid
}

ipcMain.handle('desktop-control', async (event, payload = {}) => {
  const action = String(payload.action || '').trim()
  if (!action) return { ok: false, error: 'Missing action' }

  if (action === 'status') {
    return {
      ok: true,
      platform: process.platform,
      xdotool: hasXdotool(),
      guiControl: process.platform === 'linux' ? hasXdotool() : process.platform === 'darwin',
      launchSupported: true,
      shellSupported: true,
    }
  }

  if (action === 'launch') {
    const command = String(payload.command || '').trim()
    const argsText = String(payload.args || '').trim()
    const cwd = String(payload.cwd || '').trim() || undefined
    if (!command) return { ok: false, error: 'Please provide a program or command to launch.' }
    const fullCommand = [command, argsText].filter(Boolean).join(' ')
    const pid = spawnDetached(fullCommand, [], { cwd, shell: true, env: process.env })
    return { ok: true, pid, launched: command, args: argsText }
  }

  if (action === 'command') {
    const command = String(payload.command || '').trim()
    const cwd = String(payload.cwd || '').trim() || undefined
    if (!command) return { ok: false, error: 'Please provide a shell command.' }
    const pid = spawnDetached(command, [], { cwd, shell: true, env: process.env })
    return { ok: true, pid }
  }

  if (!hasXdotool()) {
    return { ok: false, error: 'Für Maus- und Tastatursteuerung benötigst du unter Linux xdotool.' }
  }

  const runXdotool = (...args) => {
    const result = spawnSync('xdotool', args, { encoding: 'utf8' })
    if (result.status !== 0) {
      throw new Error(String(result.stderr || result.stdout || 'xdotool failed').trim())
    }
    return result.stdout || ''
  }

  try {
    if (action === 'key') {
      const keys = String(payload.keys || '').trim()
      if (!keys) return { ok: false, error: 'Please provide keys.' }
      runXdotool('key', keys)
      return { ok: true }
    }

    if (action === 'type') {
      const text = String(payload.text || '')
      if (!text) return { ok: false, error: 'Please provide text.' }
      runXdotool('type', '--delay', '1', text)
      return { ok: true }
    }

    if (action === 'click') {
      const button = String(payload.button || '1').trim()
      const x = payload.x
      const y = payload.y
      if (Number.isFinite(Number(x)) && Number.isFinite(Number(y))) {
        runXdotool('mousemove', String(Number(x)), String(Number(y)), 'click', button)
      } else {
        runXdotool('click', button)
      }
      return { ok: true }
    }

    if (action === 'scroll') {
      const direction = String(payload.direction || 'down').toLowerCase()
      const amount = Math.max(1, Math.min(20, Number(payload.amount || 1)))
      const button = direction === 'up' ? '4' : direction === 'left' ? '6' : direction === 'right' ? '7' : '5'
      for (let index = 0; index < amount; index += 1) {
        runXdotool('click', button)
      }
      return { ok: true }
    }

    if (action === 'move') {
      const x = Number(payload.x)
      const y = Number(payload.y)
      if (!Number.isFinite(x) || !Number.isFinite(y)) return { ok: false, error: 'Please provide coordinates.' }
      runXdotool('mousemove', String(x), String(y))
      return { ok: true }
    }

    return { ok: false, error: `Unsupported action: ${action}` }
  } catch (error) {
    return { ok: false, error: error.message }
  }
})

// collect renderer console errors
const logPath = path.join(__dirname, '.logs')
try { fs.mkdirSync(logPath, { recursive: true }) } catch (e) {}
const logFile = path.join(logPath, 'renderer.log')
ipcMain.on('renderer-log', (event, msg) => {
  try { fs.appendFileSync(logFile, `[${new Date().toISOString()}] ${msg}\n`) } catch (e) {}
})

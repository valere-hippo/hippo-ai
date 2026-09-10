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

function isProbablyTextFile(filename) {
  const ext = path.extname(String(filename || '')).toLowerCase()
  return new Set(['.txt', '.md', '.markdown', '.csv', '.json', '.yml', '.yaml', '.xml', '.rtf', '.log', '.ini', '.py', '.js', '.ts', '.html', '.htm', '.css']).has(ext)
}

function summarizeLocalFolder(folderPath, options = {}) {
  const maxTextChars = Number.isFinite(options.maxTextChars) ? options.maxTextChars : 12000
  const root = String(folderPath || '').trim()
  if (!root) return { ok: false, context: 'Kein Ordnerpfad angegeben.' }
  if (!fs.existsSync(root) || !fs.statSync(root).isDirectory()) {
    return { ok: false, context: `Der Ordner ist nicht erreichbar: ${root}` }
  }

  const lines = [`Lokaler gemeinsamer Ordner (vom Desktop gelesen): ${root}`]
  let chars = 0

  const walk = (dir, depth = 0) => {
    let entries = []
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true })
    } catch (error) {
      lines.push(`${'  '.repeat(depth)}- [Fehler beim Lesen] ${dir}: ${error.message}`)
      return
    }

    const sorted = entries.slice().sort((a, b) => a.name.localeCompare(b.name, 'de'))
    const relDir = path.relative(root, dir) || '.'
    lines.push(`${'  '.repeat(depth)}[Ordner] ${relDir}`)

    for (const entry of sorted) {
      const absPath = path.join(dir, entry.name)
      const relPath = path.relative(root, absPath) || entry.name
      if (entry.isDirectory()) {
        walk(absPath, depth + 1)
        continue
      }
      if (!entry.isFile()) continue

      let line = `${'  '.repeat(depth + 1)}- ${relPath}`
      try {
        const stat = fs.statSync(absPath)
        line += ` (${stat.size} bytes)`
        if (isProbablyTextFile(entry.name)) {
          const raw = fs.readFileSync(absPath, 'utf8')
          const preview = raw.replace(/\s+/g, ' ').trim().slice(0, maxTextChars)
          if (preview) {
            line += ` | Inhalt: ${preview}`
            chars += preview.length
          }
        }
      } catch (error) {
        line += ` | nicht lesbar: ${error.message}`
      }
      lines.push(line)
    }
  }

  walk(root, 0)
  if (lines.length === 1) lines.push('Keine Dateien gefunden.')
  if (chars === 0) lines.push('Hinweis: Es wurden keine direkt lesbaren Textinhalte gefunden, aber die Dateistruktur wurde vollständig erfasst.')
  return { ok: true, context: lines.join(String.fromCharCode(10)) }
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

ipcMain.handle('inspect-project-folder', async (event, { folder, maxDepth = 2, maxEntries = 30, maxTextChars = 3000 } = {}) => {
  try {
    return summarizeLocalFolder(folder, { maxDepth, maxEntries, maxTextChars })
  } catch (error) {
    return { ok: false, context: `Fehler beim Lesen des Ordners: ${error.message}` }
  }
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

function hasOsascript() {
  if (process.platform !== 'darwin') return false
  const result = spawnSync('/usr/bin/env', ['osascript', '-e', 'return 1'], { encoding: 'utf8' })
  return result.status === 0
}

function hasPowerShell() {
  if (process.platform !== 'win32') return false
  const candidates = [
    ['powershell', ['-NoProfile', '-Command', '$PSVersionTable.PSVersion.ToString()']],
    ['pwsh', ['-NoProfile', '-Command', '$PSVersionTable.PSVersion.ToString()']],
  ]
  return candidates.some(([exe, args]) => {
    try {
      const result = spawnSync(exe, args, { encoding: 'utf8' })
      return result.status === 0
    } catch (error) {
      return false
    }
  })
}

function runWindowsPowerShell(script) {
  const candidates = [
    ['powershell', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', script]],
    ['pwsh', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', script]],
  ]
  for (const [exe, args] of candidates) {
    const result = spawnSync(exe, args, { encoding: 'utf8' })
    if (result.status === 0) {
      return { ok: true, stdout: result.stdout || '' }
    }
    if (String(result.stderr || result.stdout || '').trim()) {
      return { ok: false, error: String(result.stderr || result.stdout || 'PowerShell failed').trim() }
    }
  }
  return { ok: false, error: 'PowerShell is not available.' }
}

function runMacJavaScript(script) {
  const result = spawnSync('/usr/bin/osascript', ['-l', 'JavaScript', '-e', script], { encoding: 'utf8' })
  if (result.status !== 0) {
    return { ok: false, error: String(result.stderr || result.stdout || 'osascript failed').trim() }
  }
  return { ok: true, stdout: result.stdout || '' }
}

function isCommandAllowedForProfile(profile, command) {
  const normalizedProfile = String(profile || 'generic').trim().toLowerCase() || 'generic'
  const text = String(command || '').toLowerCase()
  if (normalizedProfile === 'generic' || normalizedProfile === 'custom') return true
  const allowed = {
    qgis: [/\bqgis\b/, /qgis-ltr/, /qgis-bin/, /ogr2ogr/, /gdal/, /python/, /bash/, /sh/],
    fledermaus: [/fledermaus/, /bat/, /bioacoustics/, /python/, /bash/, /sh/],
    bioacoustics: [/fledermaus/, /bat/, /bioacoustics/, /python/, /bash/, /sh/],
  }
  const rules = allowed[normalizedProfile] || []
  return rules.some((rule) => rule.test(text))
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
      supports: {
        linuxXdotool: process.platform === 'linux' && hasXdotool(),
        macAutomation: process.platform === 'darwin' && hasOsascript(),
        windowsAutomation: process.platform === 'win32' && hasPowerShell(),
      },
      launchSupported: true,
      shellSupported: true,
    }
  }

  if (action === 'launch' || action === 'command') {
    const command = String(payload.command || '').trim()
    const argsText = String(payload.args || '').trim()
    const cwd = String(payload.cwd || '').trim() || undefined
    const profile = String(payload.profile || 'generic').trim().toLowerCase() || 'generic'
    if (!command) return { ok: false, error: action === 'launch' ? 'Please provide a program or command to launch.' : 'Please provide a shell command.' }
    if (!isCommandAllowedForProfile(profile, command)) {
      return { ok: false, error: `Der Befehl ist im Profil ${profile} nicht erlaubt.` }
    }
    const fullCommand = action === 'launch' ? [command, argsText].filter(Boolean).join(' ') : command
    const pid = spawnDetached(fullCommand, [], { cwd, shell: true, env: process.env })
    return { ok: true, pid, launched: command, args: argsText }
  }

  if (action === 'type') {
    const original = clipboard.readText()
    const textValue = String(payload.text || '')
    clipboard.writeText(textValue)
    try {
      if (process.platform === 'win32') {
        const result = runWindowsPowerShell('Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.SendKeys]::SendWait("^v");')
        if (!result.ok) return result
        return { ok: true }
      }
      if (process.platform === 'darwin') {
        const result = runMacJavaScript('const app = Application("System Events"); app.keystroke("v", { using: ["command down"] });')
        if (!result.ok) return result
        return { ok: true }
      }
      if (hasXdotool()) {
        const result = spawnSync('xdotool', ['type', '--delay', '1', textValue], { encoding: 'utf8' })
        if (result.status !== 0) return { ok: false, error: String(result.stderr || result.stdout || 'xdotool type failed').trim() }
        return { ok: true }
      }
      return { ok: false, error: 'Keine Paste-/Type-Methode verfügbar.' }
    } finally {
      setTimeout(() => {
        try { clipboard.writeText(original) } catch (error) {}
      }, 150)
    }
  }

  if (action === 'key') {
    const keys = String(payload.keys || '').trim()
    if (!keys) return { ok: false, error: 'Please provide keys.' }
    if (process.platform === 'win32') {
      const { modifiers, base } = parseShortcutInput(keys)
      const modifierMap = { ctrl: '^', control: '^', shift: '+', alt: '%', option: '%', cmd: '#', win: '#', meta: '#' }
      const keyMap = { enter: '{ENTER}', return: '{ENTER}', tab: '{TAB}', escape: '{ESC}', esc: '{ESC}', backspace: '{BACKSPACE}', delete: '{DELETE}', del: '{DELETE}', space: ' ', left: '{LEFT}', right: '{RIGHT}', up: '{UP}', down: '{DOWN}', home: '{HOME}', end: '{END}', pageup: '{PGUP}', pagedown: '{PGDN}', f1: '{F1}', f2: '{F2}', f3: '{F3}', f4: '{F4}', f5: '{F5}', f6: '{F6}', f7: '{F7}', f8: '{F8}', f9: '{F9}', f10: '{F10}', f11: '{F11}', f12: '{F12}' }
      const prefix = modifiers.map((item) => modifierMap[item] || '').join('')
      const token = keyMap[base] || base
      const sequence = `${prefix}${token}`
      const result = runWindowsPowerShell(`Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.SendKeys]::SendWait(${JSON.stringify(sequence)});`)
      return result.ok ? { ok: true } : result
    }
    if (process.platform === 'darwin') {
      const result = runMacJavaScript(`
ObjC.import('ApplicationServices');
const systemEvents = Application('System Events');
const shortcut = ${JSON.stringify(keys)};
function parseShortcut(input) {
  const parts = String(input || '').split('+').map((part) => part.trim()).filter(Boolean);
  const base = (parts.pop() || '').toLowerCase();
  const modifiers = parts.map((part) => part.toLowerCase());
  return { base, modifiers };
}
function modifiersToUsing(mods) {
  return mods.map((modifier) => {
    if (modifier === 'ctrl' || modifier === 'control') return 'control down';
    if (modifier === 'shift') return 'shift down';
    if (modifier === 'alt' || modifier === 'option') return 'option down';
    if (modifier === 'cmd' || modifier === 'command' || modifier === 'meta') return 'command down';
    return null;
  }).filter(Boolean);
}
const parsed = parseShortcut(shortcut);
const codeMap = { enter: 36, return: 36, tab: 48, space: 49, backspace: 51, delete: 51, del: 51, escape: 53, esc: 53, left: 123, right: 124, down: 125, up: 126, home: 115, end: 119, pageup: 116, pagedown: 121, f1: 122, f2: 120, f3: 99, f4: 118, f5: 96, f6: 97, f7: 98, f8: 100, f9: 101, f10: 109, f11: 103, f12: 111 };
const using = modifiersToUsing(parsed.modifiers);
if (codeMap[parsed.base] != null) {
  systemEvents.keyCode(codeMap[parsed.base], { using });
} else {
  systemEvents.keystroke(parsed.base.length === 1 ? parsed.base : String(parsed.base || ''), { using });
}
`)
      return result.ok ? { ok: true } : result
    }
    if (hasXdotool()) {
      const result = spawnSync('xdotool', ['key', keys], { encoding: 'utf8' })
      if (result.status !== 0) return { ok: false, error: String(result.stderr || result.stdout || 'xdotool key failed').trim() }
      return { ok: true }
    }
    return { ok: false, error: 'Keine Tastatur-Methode verfügbar.' }
  }

  if (action === 'move' || action === 'click' || action === 'scroll') {
    if (process.platform === 'win32' && hasPowerShell()) {
      if (action === 'move' || action === 'click') {
        const step = { action, button: payload.button || '1', x: payload.x, y: payload.y }
        const result = runWindowsPowerShell(`
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class HippoMouse {
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);
}
"@
$step = ConvertFrom-Json @'
${JSON.stringify(step)}
'@
$button = [int]($step.button ?? 1)
$flagsDown = 0
$flagsUp = 0
switch ($button) {
  2 { $flagsDown = 0x0008; $flagsUp = 0x0010 }
  3 { $flagsDown = 0x0002; $flagsUp = 0x0004 }
  Default { $flagsDown = 0x0002; $flagsUp = 0x0004 }
}
if ($step.x -ne $null -and $step.y -ne $null) {
  [HippoMouse]::SetCursorPos([int]$step.x, [int]$step.y) | Out-Null
}
if ($step.action -eq 'move') { return }
[HippoMouse]::mouse_event([uint32]$flagsDown, 0, 0, 0, [UIntPtr]::Zero)
[HippoMouse]::mouse_event([uint32]$flagsUp, 0, 0, 0, [UIntPtr]::Zero)
`)
        return result.ok ? { ok: true } : result
      }
      const delta = Math.max(1, Math.min(20, Number(payload.amount || 1))) * 120 * (String(payload.direction || 'down').toLowerCase() === 'up' ? 1 : -1)
      const result = runWindowsPowerShell(`
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class HippoMouse {
  [DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);
}
"@
[HippoMouse]::mouse_event(0x0800, 0, 0, [uint32](${delta}), [UIntPtr]::Zero)
`)
      return result.ok ? { ok: true } : result
    }

    if (process.platform === 'darwin' && hasOsascript()) {
      if (action === 'move' || action === 'click') {
        const step = { action, button: payload.button || '1', x: payload.x, y: payload.y }
        const result = runMacJavaScript(`
ObjC.import('ApplicationServices');
const step = ${JSON.stringify(step)};
function point(x, y) {
  return $.CGPointMake(Number(x), Number(y));
}
function buttonValue(button) {
  const value = Number(button || 1);
  if (value === 2) return $.kCGMouseButtonCenter;
  if (value === 3) return $.kCGMouseButtonRight;
  return $.kCGMouseButtonLeft;
}
function post(type, x, y, button) {
  const event = $.CGEventCreateMouseEvent(null, type, point(x, y), button);
  $.CGEventPost($.kCGHIDEventTap, event);
}
const x = step.x != null ? Number(step.x) : 0;
const y = step.y != null ? Number(step.y) : 0;
const button = buttonValue(step.button);
if (step.action === 'move') {
  post($.kCGEventMouseMoved, x, y, $.kCGMouseButtonLeft);
} else {
  if (step.x != null && step.y != null) {
    post($.kCGEventMouseMoved, x, y, $.kCGMouseButtonLeft);
  }
  post($.kCGEventLeftMouseDown, x, y, button);
  post($.kCGEventLeftMouseUp, x, y, button);
}
`)
        return result.ok ? { ok: true } : result
      }
      const result = runMacJavaScript(`
ObjC.import('ApplicationServices');
const amount = Math.max(1, Math.min(20, Number(${Number(payload.amount || 1)})));
const direction = ${JSON.stringify(String(payload.direction || 'down').toLowerCase())};
const signedY = direction === 'up' ? amount : -amount;
const signedX = direction === 'left' ? amount : direction === 'right' ? -amount : 0;
const event = $.CGEventCreateScrollWheelEvent(null, $.kCGScrollEventUnitLine, 2, signedY, signedX);
$.CGEventPost($.kCGHIDEventTap, event);
`)
      return result.ok ? { ok: true } : result
    }

    if (hasXdotool()) {
      if (action === 'move') {
        const x = Number(payload.x)
        const y = Number(payload.y)
        if (!Number.isFinite(x) || !Number.isFinite(y)) return { ok: false, error: 'Please provide coordinates.' }
        const result = spawnSync('xdotool', ['mousemove', String(x), String(y)], { encoding: 'utf8' })
        if (result.status !== 0) return { ok: false, error: String(result.stderr || result.stdout || 'xdotool move failed').trim() }
        return { ok: true }
      }
      if (action === 'click') {
        const button = String(payload.button || '1').trim()
        const x = payload.x
        const y = payload.y
        const args = Number.isFinite(Number(x)) && Number.isFinite(Number(y))
          ? ['mousemove', String(Number(x)), String(Number(y)), 'click', button]
          : ['click', button]
        const result = spawnSync('xdotool', args, { encoding: 'utf8' })
        if (result.status !== 0) return { ok: false, error: String(result.stderr || result.stdout || 'xdotool click failed').trim() }
        return { ok: true }
      }
      const direction = String(payload.direction || 'down').toLowerCase()
      const amount = Math.max(1, Math.min(20, Number(payload.amount || 1)))
      const button = direction === 'up' ? '4' : direction === 'left' ? '6' : direction === 'right' ? '7' : '5'
      for (let index = 0; index < amount; index += 1) {
        const result = spawnSync('xdotool', ['click', button], { encoding: 'utf8' })
        if (result.status !== 0) return { ok: false, error: String(result.stderr || result.stdout || 'xdotool scroll failed').trim() }
      }
      return { ok: true }
    }

    return { ok: false, error: 'Keine Maus-/Scroll-Methode verfügbar.' }
  }

  return { ok: false, error: `Unsupported action: ${action}` }
})

// collect renderer console errors
const logPath = path.join(__dirname, '.logs')
try { fs.mkdirSync(logPath, { recursive: true }) } catch (e) {}
const logFile = path.join(logPath, 'renderer.log')
ipcMain.on('renderer-log', (event, msg) => {
  try { fs.appendFileSync(logFile, `[${new Date().toISOString()}] ${msg}\n`) } catch (e) {}
})

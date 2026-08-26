const { app, BrowserWindow, Menu, ipcMain, dialog } = require('electron')
const path = require('path')
const fs = require('fs')

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
  createWindow()
  app.on('activate', function () {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', function () {
  if (process.platform !== 'darwin') app.quit()
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
    fs.writeFileSync(filePath, data, 'utf8')
    return { ok: true, path: filePath }
  }catch(e){ return { ok: false, error: e.message } }
})

// collect renderer console errors
const logPath = path.join(__dirname, '.logs')
try { fs.mkdirSync(logPath, { recursive: true }) } catch (e) {}
const logFile = path.join(logPath, 'renderer.log')
ipcMain.on('renderer-log', (event, msg) => {
  try { fs.appendFileSync(logFile, `[${new Date().toISOString()}] ${msg}\n`) } catch (e) {}
})

const fs = require('fs')
const os = require('os')
const path = require('path')
const crypto = require('crypto')
const { Worker, isMainThread, parentPort, workerData } = require('worker_threads')

const TEXT_EXTENSIONS = new Set(['.txt', '.md', '.markdown', '.csv', '.json', '.yml', '.yaml', '.xml', '.rtf', '.log', '.ini', '.py', '.js', '.ts', '.html', '.htm', '.css'])

function isProbablyTextFile(filename) {
  const ext = path.extname(String(filename || '')).toLowerCase()
  return TEXT_EXTENSIONS.has(ext)
}

function readTextContent(filePath, maxTextChars) {
  const encodings = ['utf8', 'utf16le', 'latin1']
  for (const encoding of encodings) {
    try {
      const rawContent = fs.readFileSync(filePath, encoding)
      const normalized = String(rawContent || '').replace(/\u0000/g, '')
      if (!normalized.trim()) continue
      if (normalized.length <= maxTextChars) return normalized
      return `${normalized.slice(0, maxTextChars)}\n… [gekürzt]`
    } catch (error) {
      // try next encoding
    }
  }
  return ''
}

function summarizeLocalFolder(folderPath, options = {}) {
  const maxDepth = Number.isFinite(options.maxDepth) ? options.maxDepth : 3
  const maxEntries = Number.isFinite(options.maxEntries) ? options.maxEntries : 120
  const maxTextChars = Number.isFinite(options.maxTextChars) ? options.maxTextChars : 50000
  const raw = String(folderPath || '').trim()
  if (!raw) return { ok: false, context: 'Kein Ordnerpfad angegeben.' }
  const roots = raw
    .split(/[\n;]+/)
    .map((value) => value.trim())
    .filter(Boolean)
  if (!roots.length) return { ok: false, context: 'Kein Ordnerpfad angegeben.' }

  const lines = [`Lokale Projektordner (vom Desktop gelesen): ${roots.join(' | ')}`]
  let chars = 0
  let entries = 0

  const pushContent = (content) => {
    if (!content) return ''
    chars += content.length
    return content
  }

  const recordFile = (filePath, depth, labelPrefix = '') => {
    if (entries >= maxEntries) return
    const indent = '  '.repeat(depth)
    const baseName = path.basename(filePath)
    let line = `${indent}- ${labelPrefix}${baseName}`
    try {
      const stat = fs.statSync(filePath)
      line += ` (${stat.size} bytes)`
      if (isProbablyTextFile(baseName)) {
        const content = readTextContent(filePath, maxTextChars)
        if (content) {
          line += `\n${indent}  [Inhalt]\n${content.split('\n').map((part) => `${indent}  ${part}`).join('\n')}`
          pushContent(content)
        } else {
          line += `\n${indent}  [Inhalt] leer oder nicht lesbar`
        }
      }
    } catch (error) {
      line += ` | nicht lesbar: ${error.message}`
    }
    lines.push(line)
    entries += 1
  }

  const walk = (dir, depth = 0, rootLabel = '') => {
    if (entries >= maxEntries || depth > maxDepth) return
    let dirEntries = []
    try {
      dirEntries = fs.readdirSync(dir, { withFileTypes: true })
    } catch (error) {
      lines.push(`${'  '.repeat(depth)}- [Fehler beim Lesen] ${dir}: ${error.message}`)
      return
    }

    const sorted = dirEntries.slice().sort((a, b) => a.name.localeCompare(b.name, 'de'))
    const relDir = path.relative(roots[0], dir) || '.'
    lines.push(`${'  '.repeat(depth)}[Ordner] ${relDir}`)

    for (const entry of sorted) {
      if (entries >= maxEntries) break
      const absPath = path.join(dir, entry.name)
      if (entry.isDirectory()) {
        lines.push(`${'  '.repeat(depth + 1)}[Ordner] ${entry.name}`)
        entries += 1
        walk(absPath, depth + 1, rootLabel)
        continue
      }
      if (!entry.isFile()) continue
      const label = rootLabel ? `${rootLabel}/` : ''
      recordFile(absPath, depth + 1, label)
    }
  }

  for (const root of roots) {
    if (entries >= maxEntries) break
    if (!fs.existsSync(root)) {
      lines.push(`- Der Ordner ist nicht erreichbar: ${root}`)
      continue
    }

    const stat = fs.statSync(root)
    if (stat.isFile()) {
      recordFile(root, 0)
      continue
    }
    if (!stat.isDirectory()) {
      lines.push(`- Der Pfad ist weder Datei noch Ordner: ${root}`)
      continue
    }

    walk(root, 0, path.basename(root))
  }

  if (lines.length === 1) lines.push('Keine Dateien gefunden.')
  if (chars === 0) lines.push('Hinweis: Es wurden keine direkt lesbaren Textinhalte gefunden, aber die Dateistruktur wurde vollständig erfasst.')
  if (entries >= maxEntries) lines.push('Hinweis: Die Auflistung wurde zur Laufzeitbegrenzung gekürzt.')
  return { ok: true, context: lines.join(String.fromCharCode(10)) }
}

function safeStat(targetPath) {
  try {
    return fs.statSync(targetPath)
  } catch (error) {
    return null
  }
}

function isDirectory(targetPath) {
  const stat = safeStat(targetPath)
  return Boolean(stat && stat.isDirectory())
}

function collectRoots(folderPath) {
  const raw = String(folderPath || '').trim()
  return raw.split(/[\n;]+/).map((value) => value.trim()).filter(Boolean)
}

function depthOf(relativePath) {
  const normalized = String(relativePath || '').replace(/\\/g, '/').replace(/^\/+|\/+$/g, '')
  if (!normalized) return 0
  return normalized.split('/').filter(Boolean).length - 1
}

function priorityScore(entry) {
  const rel = String(entry?.relative_path || '')
  const ext = path.extname(rel).toLowerCase()
  const preferred = TEXT_EXTENSIONS
  return [depthOf(rel), preferred.has(ext) ? 0 : 1, rel.length, rel.toLowerCase()]
}

function sortFiles(files) {
  return files.slice().sort((a, b) => {
    const [da, pa, la, na] = priorityScore(a)
    const [db, pb, lb, nb] = priorityScore(b)
    if (da !== db) return da - db
    if (pa !== pb) return pa - pb
    if (la !== lb) return la - lb
    return String(na).localeCompare(String(nb), 'de')
  })
}

function scanRoot(root, options = {}) {
  const maxDepth = Number.isFinite(options.maxDepth) ? options.maxDepth : Infinity
  const maxFiles = Number.isFinite(options.maxFiles) ? options.maxFiles : Infinity
  const files = []

  const walk = (dir, depth = 0) => {
    if (files.length >= maxFiles || depth > maxDepth) return
    let entries = []
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true })
    } catch (error) {
      return
    }

    const sorted = entries.slice().sort((a, b) => a.name.localeCompare(b.name, 'de'))
    for (const entry of sorted) {
      if (files.length >= maxFiles) return
      const absPath = path.join(dir, entry.name)
      if (entry.isDirectory()) {
        walk(absPath, depth + 1)
        continue
      }
      if (!entry.isFile()) continue
      try {
        const stat = fs.statSync(absPath)
        files.push({
          root,
          path: absPath,
          relative_path: path.relative(root, absPath).split(path.sep).join('/'),
          size: stat.size,
          modified_at: stat.mtime.toISOString(),
        })
      } catch (error) {
        // ignore unreadable entries
      }
    }
  }

  if (isDirectory(root)) {
    walk(root, 0)
  }

  return { ok: true, files: sortFiles(files), truncated: files.length >= maxFiles }
}

function cacheKeyFor(roots, options = {}) {
  const hash = crypto.createHash('sha1')
  hash.update(JSON.stringify({
    roots: roots.map((root) => {
      const stat = safeStat(root)
      return {
        root,
        exists: Boolean(stat),
        mtimeMs: stat ? stat.mtimeMs : 0,
        size: stat ? stat.size : 0,
      }
    }),
    maxDepth: Number.isFinite(options.maxDepth) ? options.maxDepth : null,
    maxFiles: Number.isFinite(options.maxFiles) ? options.maxFiles : null,
  }))
  return hash.digest('hex')
}

function readCachedResult(cacheDir, cacheKey, ttlMs) {
  if (!cacheDir) return null
  const filePath = path.join(cacheDir, `${cacheKey}.json`)
  try {
    if (!fs.existsSync(filePath)) return null
    const stat = fs.statSync(filePath)
    if (Number.isFinite(ttlMs) && ttlMs > 0) {
      const age = Date.now() - stat.mtimeMs
      if (age > ttlMs) return null
    }
    const parsed = JSON.parse(fs.readFileSync(filePath, 'utf8'))
    if (!parsed || typeof parsed !== 'object') return null
    if (parsed.cacheKey !== cacheKey || !Array.isArray(parsed.files)) return null
    return {
      ok: true,
      files: parsed.files,
      truncated: Boolean(parsed.truncated),
      cached: true,
    }
  } catch (error) {
    return null
  }
}

function writeCachedResult(cacheDir, cacheKey, result) {
  if (!cacheDir) return
  try {
    fs.mkdirSync(cacheDir, { recursive: true })
    const filePath = path.join(cacheDir, `${cacheKey}.json`)
    const payload = {
      cacheKey,
      updatedAt: new Date().toISOString(),
      truncated: Boolean(result?.truncated),
      files: Array.isArray(result?.files) ? result.files : [],
    }
    fs.writeFileSync(filePath, JSON.stringify(payload))
  } catch (error) {
    // ignore cache write errors
  }
}

async function scanFolder(folderPath, options = {}) {
  const roots = collectRoots(folderPath)
  const maxFiles = Number.isFinite(options.maxFiles) ? options.maxFiles : Infinity
  const concurrency = Math.max(1, Number.isFinite(options.concurrency) ? options.concurrency : Math.min(4, os.cpus().length || 2))
  const cacheDir = String(options.cacheDir || '').trim()
  const ttlMs = Number.isFinite(options.ttlMs) ? options.ttlMs : 5 * 60 * 1000
  const key = roots.length ? cacheKeyFor(roots, options) : ''
  const cached = key ? readCachedResult(cacheDir, key, ttlMs) : null
  if (cached) {
    return cached
  }

  if (roots.length <= 1 || concurrency === 1) {
    const files = []
    for (const root of roots) {
      const result = scanRoot(root, options)
      files.push(...(Array.isArray(result.files) ? result.files : []))
      if (files.length >= maxFiles) break
    }
    const result = { ok: true, files: sortFiles(files).slice(0, maxFiles), truncated: files.length >= maxFiles }
    if (key) writeCachedResult(cacheDir, key, result)
    return result
  }

  const queue = roots.slice()
  const files = []
  const active = []

  const runWorker = () => new Promise((resolve) => {
    const root = queue.shift()
    if (!root) {
      resolve([])
      return
    }
    const worker = new Worker(__filename, {
      workerData: { root, options },
    })
    worker.once('message', (message) => {
      resolve(Array.isArray(message?.files) ? message.files : [])
    })
    worker.once('error', () => resolve([]))
    worker.once('exit', () => {})
  })

  while (queue.length || active.length) {
    while (queue.length && active.length < concurrency) {
      const promise = runWorker().then((chunk) => {
        files.push(...chunk)
        const index = active.indexOf(promise)
        if (index >= 0) active.splice(index, 1)
      })
      active.push(promise)
    }
    if (active.length) {
      await Promise.race(active)
    }
  }

  const result = { ok: true, files: sortFiles(files).slice(0, maxFiles), truncated: files.length >= maxFiles }
  if (key) writeCachedResult(cacheDir, key, result)
  return result
}

if (!isMainThread) {
  const result = scanRoot(workerData?.root, workerData?.options || {})
  parentPort.postMessage(result)
}

module.exports = {
  summarizeLocalFolder,
  scanFolder,
  isProbablyTextFile,
}

if (require.main === module) {
  const folder = process.argv[2] || ''
  let options = {}
  try {
    options = JSON.parse(process.argv[3] || '{}')
  } catch (error) {
    options = {}
  }

  const mode = String(options.mode || '').toLowerCase()
  const runner = mode === 'inspect' ? summarizeLocalFolder : scanFolder
  Promise.resolve(runner(folder, options))
    .then((result) => process.stdout.write(JSON.stringify(result)))
    .catch((error) => process.stdout.write(JSON.stringify({ ok: false, error: error.message })))
}

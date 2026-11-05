const fs = require('fs')
const os = require('os')
const path = require('path')
const { Worker, isMainThread, parentPort, workerData } = require('worker_threads')

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

  if (fs.existsSync(root)) {
    try {
      const stat = fs.statSync(root)
      if (stat.isDirectory()) {
        walk(root, 0)
      }
    } catch (error) {
      // ignore invalid roots
    }
  }

  return { ok: true, files, truncated: files.length >= maxFiles }
}

function collectRoots(folderPath) {
  const raw = String(folderPath || '').trim()
  return raw.split(/[\n;]+/).map((value) => value.trim()).filter(Boolean)
}

async function scanFolder(folderPath, options = {}) {
  const roots = collectRoots(folderPath)
  const maxFiles = Number.isFinite(options.maxFiles) ? options.maxFiles : Infinity
  const concurrency = Math.max(1, Number.isFinite(options.concurrency) ? options.concurrency : Math.min(4, os.cpus().length || 2))
  if (roots.length <= 1 || concurrency === 1) {
    const files = []
    for (const root of roots) {
      const result = scanRoot(root, options)
      files.push(...(Array.isArray(result.files) ? result.files : []))
      if (files.length >= maxFiles) break
    }
    return { ok: true, files: files.slice(0, maxFiles), truncated: files.length >= maxFiles }
  }

  const queue = roots.slice()
  const files = []
  const workers = []

  const runWorker = () => new Promise((resolve) => {
    const root = queue.shift()
    if (!root) {
      resolve([])
      return
    }
    const worker = new Worker(__filename, {
      workerData: { root, options },
    })
    workers.push(worker)
    worker.once('message', (message) => {
      resolve(Array.isArray(message?.files) ? message.files : [])
    })
    worker.once('error', () => resolve([]))
    worker.once('exit', () => {})
  })

  const active = []
  while (queue.length || active.length) {
    while (queue.length && active.length < concurrency) {
      const promise = runWorker().then((chunk) => {
        files.push(...chunk)
        active.splice(active.indexOf(promise), 1)
      })
      active.push(promise)
    }
    if (active.length) {
      await Promise.race(active)
    }
  }

  return { ok: true, files: files.slice(0, maxFiles), truncated: files.length >= maxFiles }
}

if (!isMainThread) {
  const result = scanRoot(workerData?.root, workerData?.options || {})
  parentPort.postMessage(result)
} else {
  const folder = process.argv[2] || ''
  let options = {}
  try {
    options = JSON.parse(process.argv[3] || '{}')
  } catch (error) {
    options = {}
  }

  scanFolder(folder, options)
    .then((result) => process.stdout.write(JSON.stringify(result)))
    .catch((error) => process.stdout.write(JSON.stringify({ ok: false, error: error.message })))
}

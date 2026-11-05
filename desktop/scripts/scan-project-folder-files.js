const fs = require('fs')
const path = require('path')

function scanFolder(folderPath, options = {}) {
  const raw = String(folderPath || '').trim()
  const roots = raw.split(/[\n;]+/).map((value) => value.trim()).filter(Boolean)
  const maxDepth = Number.isFinite(options.maxDepth) ? options.maxDepth : Infinity
  const maxFiles = Number.isFinite(options.maxFiles) ? options.maxFiles : Infinity
  const files = []

  const walk = (root, dir, depth = 0) => {
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
        walk(root, absPath, depth + 1)
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

  for (const root of roots) {
    if (files.length >= maxFiles) break
    if (!fs.existsSync(root)) continue
    let stat
    try {
      stat = fs.statSync(root)
    } catch (error) {
      continue
    }
    if (!stat.isDirectory()) continue
    walk(root, root, 0)
  }

  return { ok: true, files, truncated: files.length >= maxFiles }
}

const folder = process.argv[2] || ''
let options = {}
try {
  options = JSON.parse(process.argv[3] || '{}')
} catch (error) {
  options = {}
}

const result = scanFolder(folder, options)
process.stdout.write(JSON.stringify(result))

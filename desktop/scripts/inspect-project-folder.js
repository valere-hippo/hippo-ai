const fs = require('fs')
const path = require('path')

function isProbablyTextFile(filename) {
  const ext = path.extname(String(filename || '')).toLowerCase()
  return new Set(['.txt', '.md', '.markdown', '.csv', '.json', '.yml', '.yaml', '.xml', '.rtf', '.log', '.ini', '.py', '.js', '.ts', '.html', '.htm', '.css']).has(ext)
}

function summarizeLocalFolder(folderPath, options = {}) {
  const maxTextChars = Number.isFinite(options.maxTextChars) ? options.maxTextChars : 12000
  const raw = String(folderPath || '').trim()
  if (!raw) return { ok: false, context: 'Kein Ordnerpfad angegeben.' }
  const roots = raw
    .split(/[\n;]+/)
    .map((value) => value.trim())
    .filter(Boolean)
  if (!roots.length) return { ok: false, context: 'Kein Ordnerpfad angegeben.' }

  const lines = [`Lokale Projektordner (vom Desktop gelesen): ${roots.join(' | ')}`]
  let chars = 0

  const walk = (root, dir, depth = 0) => {
    let entries = []
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true })
    } catch (error) {
      lines.push(`${'  '.repeat(depth)}- [Fehler beim Lesen] ${dir}: ${error.message}`)
      return
    }

    const sorted = entries.slice().sort((a, b) => a.name.localeCompare(b.name, 'de'))
    const relDir = path.relative(root, dir) || '.'
    lines.push(`${'  '.repeat(depth)}[Ordner] ${path.basename(root)} / ${relDir}`)

    for (const entry of sorted) {
      const absPath = path.join(dir, entry.name)
      const relPath = path.relative(root, absPath) || entry.name
      if (entry.isDirectory()) {
        walk(root, absPath, depth + 1)
        continue
      }
      if (!entry.isFile()) continue

      let line = `${'  '.repeat(depth + 1)}- ${path.basename(root)}/${relPath}`
      try {
        const stat = fs.statSync(absPath)
        line += ` (${stat.size} bytes)`
        if (isProbablyTextFile(entry.name)) {
          const rawContent = fs.readFileSync(absPath, 'utf8')
          const preview = rawContent.replace(/\s+/g, ' ').trim().slice(0, maxTextChars)
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

  for (const root of roots) {
    if (!fs.existsSync(root) || !fs.statSync(root).isDirectory()) {
      lines.push(`- Der Ordner ist nicht erreichbar: ${root}`)
      continue
    }
    walk(root, root, 0)
  }
  if (lines.length === 1) lines.push('Keine Dateien gefunden.')
  if (chars === 0) lines.push('Hinweis: Es wurden keine direkt lesbaren Textinhalte gefunden, aber die Dateistruktur wurde vollständig erfasst.')
  return { ok: true, context: lines.join(String.fromCharCode(10)) }
}

const folder = process.argv[2] || ''
let options = {}
try {
  options = JSON.parse(process.argv[3] || '{}')
} catch (error) {
  options = {}
}

const result = summarizeLocalFolder(folder, options)
process.stdout.write(JSON.stringify(result))

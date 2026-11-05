const fs = require('fs')
const path = require('path')

function isProbablyTextFile(filename) {
  const ext = path.extname(String(filename || '')).toLowerCase()
  return new Set(['.txt', '.md', '.markdown', '.csv', '.json', '.yml', '.yaml', '.xml', '.rtf', '.log', '.ini', '.py', '.js', '.ts', '.html', '.htm', '.css']).has(ext)
}

function summarizeLocalFolder(folderPath, options = {}) {
  const maxDepth = Number.isFinite(options.maxDepth) ? options.maxDepth : 2
  const maxEntries = Number.isFinite(options.maxEntries) ? options.maxEntries : 60
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
  let entries = 0

  const walk = (dir, depth = 0) => {
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
        walk(absPath, depth + 1)
        continue
      }
      if (!entry.isFile()) continue

      let line = `${'  '.repeat(depth + 1)}- ${entry.name}`
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
      entries += 1
    }
  }

  for (const root of roots) {
    if (entries >= maxEntries) break
    if (!fs.existsSync(root) || !fs.statSync(root).isDirectory()) {
      lines.push(`- Der Ordner ist nicht erreichbar: ${root}`)
      continue
    }
    walk(root, 0)
  }

  if (lines.length === 1) lines.push('Keine Dateien gefunden.')
  if (chars === 0) lines.push('Hinweis: Es wurden keine direkt lesbaren Textinhalte gefunden, aber die Dateistruktur wurde vollständig erfasst.')
  if (entries >= maxEntries) lines.push('Hinweis: Die Auflistung wurde zur Laufzeitbegrenzung gekürzt.')
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

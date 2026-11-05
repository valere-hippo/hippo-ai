const fs = require('fs')
const path = require('path')

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

const folder = process.argv[2] || ''
let options = {}
try {
  options = JSON.parse(process.argv[3] || '{}')
} catch (error) {
  options = {}
}

const result = summarizeLocalFolder(folder, options)
process.stdout.write(JSON.stringify(result))

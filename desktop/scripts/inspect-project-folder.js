const { summarizeLocalFolder } = require('./project-folder-reader')

const folder = process.argv[2] || ''
let options = {}
try {
  options = JSON.parse(process.argv[3] || '{}')
} catch (error) {
  options = {}
}

const result = summarizeLocalFolder(folder, { ...options, mode: 'inspect' })
process.stdout.write(JSON.stringify(result))

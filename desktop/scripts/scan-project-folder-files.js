const { scanFolder } = require('./project-folder-reader')

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

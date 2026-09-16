const fs = require('fs')
const path = require('path')

const apiUrl = String(process.env.HIPPO_API_URL || 'https://hippo-api.hipposideros-cloud.de').trim()
const appPaths = {
  qgis: String(process.env.HIPPO_APP_PATH_QGIS || '').trim(),
  word: String(process.env.HIPPO_APP_PATH_WORD || '').trim(),
  excel: String(process.env.HIPPO_APP_PATH_EXCEL || '').trim(),
  libreoffice: String(process.env.HIPPO_APP_PATH_LIBREOFFICE || '').trim(),
  hipponalyze: String(process.env.HIPPO_APP_PATH_HIPPONALYZE || '').trim(),
}
const targetPath = path.join(process.cwd(), 'build-config.json')

fs.writeFileSync(
  targetPath,
  JSON.stringify(
    {
      apiUrl,
      appPaths: Object.fromEntries(Object.entries(appPaths).filter(([, value]) => value)),
    },
    null,
    2,
  ),
)

console.log(`Wrote runtime config to ${targetPath}`)

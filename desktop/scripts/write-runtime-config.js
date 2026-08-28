const fs = require('fs')
const path = require('path')

const apiUrl = String(process.env.HIPPO_API_URL || 'https://api.hipposideros-cloud.de').trim()
const targetPath = path.join(process.cwd(), 'build-config.json')

fs.writeFileSync(
  targetPath,
  JSON.stringify(
    {
      apiUrl,
    },
    null,
    2,
  ),
)

console.log(`Wrote runtime config to ${targetPath}`)

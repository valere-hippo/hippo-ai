const assert = require('assert')
const { shouldBlockFirstProjectMessage, shouldDelayProjectOpen } = require('../renderer/project-folder-readiness')

assert.strictEqual(
  shouldBlockFirstProjectMessage({
    projectId: 7,
    explicitPath: '',
    projectFolderContext: '',
    cachedState: 'idle',
    cachedContext: '',
  }),
  true,
)

assert.strictEqual(
  shouldBlockFirstProjectMessage({
    projectId: 7,
    explicitPath: '',
    projectFolderContext: 'already loaded',
    cachedState: 'ready',
    cachedContext: 'already loaded',
    deepWarmState: 'ready',
  }),
  false,
)

assert.strictEqual(
  shouldBlockFirstProjectMessage({
    projectId: 7,
    explicitPath: '',
    projectFolderContext: '',
    cachedState: 'ready',
    cachedContext: 'shallow-only',
    deepWarmState: 'loading',
  }),
  true,
)

assert.strictEqual(
  shouldDelayProjectOpen({
    projectId: 7,
    currentConversationId: null,
    projectFolderContext: '',
    deepWarmState: 'loading',
    cachedContext: '',
  }),
  true,
)

assert.strictEqual(
  shouldDelayProjectOpen({
    projectId: 7,
    currentConversationId: 99,
    projectFolderContext: '',
    deepWarmState: 'loading',
    cachedContext: '',
  }),
  false,
)

assert.strictEqual(
  shouldDelayProjectOpen({
    projectId: 7,
    currentConversationId: null,
    projectFolderContext: 'loaded',
    deepWarmState: 'loading',
    cachedContext: 'loaded',
  }),
  false,
)

console.log('ok')

function shouldBlockFirstProjectMessage({
  projectId,
  explicitPath,
  projectFolderContext,
  cachedState,
  cachedContext,
  deepWarmState,
}) {
  if (!projectId) return false
  if (explicitPath) return false
  if (String(projectFolderContext || '').trim()) return false
  if (deepWarmState === 'ready') return false
  if (cachedState === 'ready' && String(cachedContext || '').trim() && deepWarmState !== 'loading') return false
  return true
}

function shouldDelayProjectOpen({
  projectId,
  currentConversationId,
  projectFolderContext,
  deepWarmState,
  cachedContext,
}) {
  if (!projectId) return false
  if (currentConversationId) return false
  if (String(projectFolderContext || '').trim()) return false
  if (deepWarmState === 'ready' && String(cachedContext || '').trim()) return false
  return true
}

module.exports = {
  shouldBlockFirstProjectMessage,
  shouldDelayProjectOpen,
}

const DEFAULT_API = 'http://localhost:8000'

function normalizeApiBaseUrl(value) {
  const raw = String(value || '').trim()
  if (!raw) return `${DEFAULT_API}/api/v1`
  const trimmed = raw.replace(/\/+$/, '')
  return trimmed.endsWith('/api/v1') ? trimmed : `${trimmed}/api/v1`
}

const API = normalizeApiBaseUrl(
  window.electron?.runtimeConfig?.apiUrl
    || window.electron?.runtimeConfig?.apiBaseUrl
    || window.electron?.runtimeConfig?.url
    || localStorage.getItem('hippo.api.url')
    || DEFAULT_API,
)

const state = {
  token: localStorage.getItem('hippo.token') || '',
  user: null,
  projects: [],
  conversations: [],
  users: [],
  selectedProjectId: null,
  currentConversationId: null,
  draftAttachments: [],
  recording: null,
  isRecording: false,
  projectConversationMemory: new Map(),
  thinkingMessage: null,
}

const els = {
  appShell: document.getElementById('app-shell'),
  loginScreen: document.getElementById('login-screen'),
  workspaceShell: document.getElementById('workspace-shell'),
  sidebarToggle: document.getElementById('sidebar-toggle'),
  sidebarBackdrop: document.getElementById('sidebar-backdrop'),
  loginButton: document.getElementById('login'),
  email: document.getElementById('email'),
  password: document.getElementById('password'),
  loginResult: document.getElementById('login-result'),
  sidebarNewChat: document.getElementById('sidebar-new-chat'),
  projectList: document.getElementById('project-list'),
  conversationList: document.getElementById('conversation-list'),
  accountAvatar: document.getElementById('account-avatar'),
  accountName: document.getElementById('account-name'),
  accountMeta: document.getElementById('account-meta'),
  logoutBtn: document.getElementById('logout-btn'),
  profileBtn: document.getElementById('profile-btn'),
  projectEmbedBtn: document.getElementById('project-embed-btn'),
  pageTitle: document.getElementById('page-title'),
  selectedInfo: document.getElementById('selected-info'),
  projectPill: document.getElementById('project-pill'),
  rolePill: document.getElementById('role-pill'),
  chatLog: document.getElementById('chat-log'),
  emptyState: document.getElementById('empty-state'),
  attachmentPreview: document.getElementById('attachment-preview'),
  chatForm: document.getElementById('chat-form'),
  chatInput: document.getElementById('chat-input'),
  attachImageBtn: document.getElementById('attach-image-btn'),
  attachFileBtn: document.getElementById('attach-file-btn'),
  imageInput: document.getElementById('image-input'),
  fileInput: document.getElementById('file-input'),
  micBtn: document.getElementById('mic-btn'),
  sendChat: document.getElementById('send-chat'),
  voiceStatus: document.getElementById('voice-status'),
  voiceCanvas: document.getElementById('voice-canvas'),
}

function q(id) {
  return document.getElementById(id)
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function normalizeRichTextLine(line) {
  return String(line || '').replace(/\u00a0/g, ' ').trimEnd()
}

function stripRichTextMarkers(text) {
  return String(text || '')
    .replace(/\s+/g, ' ')
    .replace(/^(\*{1,3}|_{1,3})\s*/g, '')
    .replace(/\s*(\*{1,3}|_{1,3})$/g, '')
    .trim()
}

function appendInlineMarkup(parent, text) {
  const source = String(text || '')
  const tokenRe = /(`[^`]*`|\*\*[\s\S]+?\*\*|__[\s\S]+?__|\*[^*\n]+?\*|_[^_\n]+?_)/g
  let lastIndex = 0

  const appendText = (chunk) => {
    if (!chunk) return
    parent.appendChild(document.createTextNode(chunk))
  }

  for (const match of source.matchAll(tokenRe)) {
    const token = match[0]
    const start = match.index || 0
    appendText(source.slice(lastIndex, start))

    if (token.startsWith('`') && token.endsWith('`')) {
      const code = document.createElement('code')
      code.textContent = token.slice(1, -1)
      parent.appendChild(code)
    } else if ((token.startsWith('**') && token.endsWith('**')) || (token.startsWith('__') && token.endsWith('__'))) {
      const strong = document.createElement('strong')
      strong.textContent = token.slice(2, -2)
      parent.appendChild(strong)
    } else if ((token.startsWith('*') && token.endsWith('*')) || (token.startsWith('_') && token.endsWith('_'))) {
      const em = document.createElement('em')
      em.textContent = token.slice(1, -1)
      parent.appendChild(em)
    } else {
      appendText(token)
    }

    lastIndex = start + token.length
  }

  appendText(source.slice(lastIndex))
}

function isTableSeparator(line) {
  return /^\s*\|?[\s:-]+(?:\|[\s:-]+)+\|?\s*$/.test(line)
}

function renderRichContent(content) {
  const root = document.createElement('div')
  root.className = 'rich-content'

  const lines = String(content || '')
    .replace(/\r/g, '')
    .split('\n')
    .map(normalizeRichTextLine)

  let paragraph = []
  let quoteLines = []
  let codeLines = null
  let listState = null
  let tableRows = null

  const flushParagraph = () => {
    if (!paragraph.length) return
    const p = document.createElement('p')
    appendInlineMarkup(p, paragraph.join(' '))
    root.appendChild(p)
    paragraph = []
  }

  const flushQuote = () => {
    if (!quoteLines.length) return
    const blockquote = document.createElement('blockquote')
    quoteLines.forEach((quoteLine, index) => {
      const p = document.createElement('p')
      appendInlineMarkup(p, quoteLine)
      blockquote.appendChild(p)
      if (index < quoteLines.length - 1) {
        blockquote.appendChild(document.createElement('br'))
      }
    })
    root.appendChild(blockquote)
    quoteLines = []
  }

  const flushList = () => {
    if (!listState) return
    root.appendChild(listState.element)
    listState = null
  }

  const flushTable = () => {
    if (!tableRows || !tableRows.length) return
    const table = document.createElement('table')
    table.className = 'rich-table'
    const [headerRow, ...bodyRows] = tableRows
    if (headerRow) {
      const thead = document.createElement('thead')
      const tr = document.createElement('tr')
      headerRow.forEach((cell) => {
        const th = document.createElement('th')
        appendInlineMarkup(th, cell)
        tr.appendChild(th)
      })
      thead.appendChild(tr)
      table.appendChild(thead)
    }
    if (bodyRows.length) {
      const tbody = document.createElement('tbody')
      bodyRows.forEach((row) => {
        const tr = document.createElement('tr')
        row.forEach((cell) => {
          const td = document.createElement('td')
          appendInlineMarkup(td, cell)
          tr.appendChild(td)
        })
        tbody.appendChild(tr)
      })
      table.appendChild(tbody)
    }
    root.appendChild(table)
    tableRows = null
  }

  const flushAll = () => {
    flushParagraph()
    flushQuote()
    flushList()
    flushTable()
  }

  const ensureList = (type) => {
    if (!listState || listState.type !== type) {
      flushParagraph()
      flushQuote()
      flushTable()
      flushList()
      const element = document.createElement(type)
      element.className = `rich-list ${type}`
      listState = { type, element }
    }
  }

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index]
    const nextLine = lines[index + 1] || ''

    if (!line) {
      flushAll()
      continue
    }

    if (line.startsWith('```')) {
      if (codeLines) {
        const pre = document.createElement('pre')
        pre.className = 'rich-codeblock'
        const code = document.createElement('code')
        code.textContent = codeLines.join('\n')
        pre.appendChild(code)
        root.appendChild(pre)
        codeLines = null
      } else {
        flushAll()
        codeLines = []
      }
      continue
    }

    if (codeLines) {
      codeLines.push(line)
      continue
    }

    if (/^#{1,6}\s+/.test(line)) {
      flushAll()
      const level = Math.min(6, (line.match(/^#{1,6}/) || [''])[0].length)
      const heading = document.createElement(`h${level}`)
      appendInlineMarkup(heading, stripRichTextMarkers(line.replace(/^#{1,6}\s+/, '')))
      root.appendChild(heading)
      continue
    }

    if (line.startsWith('>')) {
      flushParagraph()
      flushList()
      flushTable()
      quoteLines.push(stripRichTextMarkers(line.replace(/^>\s?/, '')))
      continue
    }

    if (quoteLines.length && !line.startsWith('>')) {
      flushQuote()
    }

    const bulletMatch = line.match(/^([-*•])\s+(.+)$/)
    const numberedMatch = line.match(/^(\d+)[.)]\s+(.+)$/)

    if (bulletMatch) {
      ensureList('ul')
      const li = document.createElement('li')
      appendInlineMarkup(li, bulletMatch[2])
      listState.element.appendChild(li)
      continue
    }

    if (numberedMatch) {
      ensureList('ol')
      const li = document.createElement('li')
      appendInlineMarkup(li, numberedMatch[2])
      listState.element.appendChild(li)
      continue
    }

    if (listState) {
      flushList()
    }

    if (line.includes('|') && isTableSeparator(nextLine)) {
      flushParagraph()
      flushQuote()
      flushList()
      tableRows = []
      const headerCells = line.split('|').map((cell) => cell.trim()).filter(Boolean)
      if (headerCells.length) tableRows.push(headerCells)
      index += 1 // skip separator
      continue
    }

    if (tableRows) {
      if (line.includes('|')) {
        const cells = line.split('|').map((cell) => cell.trim()).filter(Boolean)
        if (cells.length) {
          tableRows.push(cells)
          continue
        }
      }
      flushTable()
    }

    paragraph.push(stripRichTextMarkers(line))
  }

  flushAll()
  if (codeLines) {
    const pre = document.createElement('pre')
    pre.className = 'rich-codeblock'
    const code = document.createElement('code')
    code.textContent = codeLines.join('\n')
    pre.appendChild(code)
    root.appendChild(pre)
  }

  return root
}

function initialsFromUser(user) {
  const source = (user?.full_name || user?.email || 'H').trim()
  const parts = source.split(/\s+/).filter(Boolean)
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()
  return source.slice(0, 2).toUpperCase()
}

function formatRole(role) {
  const map = {
    ADMIN: 'Administrator',
    MANAGER: 'Manager',
    USER: 'Benutzer',
    READ_ONLY: 'Nur lesen',
  }
  return map[role] || role
}

function getContextProject() {
  return state.projects.find((project) => project.id === state.selectedProjectId) || null
}

function getConversationTitle(conversation) {
  if (!conversation) return 'Neuer Chat'
  return conversation.title || conversation.preview_title || conversation.first_message || `Chat #${conversation.id}`
}

function deriveConversationTitle(message, attachments = []) {
  const base = (message || '').trim().replace(/\s+/g, ' ')
  if (base) {
    return base.length > 64 ? `${base.slice(0, 63).trim()}…` : base
  }
  const firstAttachment = attachments.find((attachment) => attachment?.filename)
  return firstAttachment?.filename || 'Neuer Chat'
}

function formatFileSize(bytes) {
  const value = Number(bytes || 0)
  if (!Number.isFinite(value) || value <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let size = value
  let unitIndex = 0
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024
    unitIndex += 1
  }
  return `${size.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`
}

function formatDateLabel(value) {
  if (!value) return 'Unbekannt'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Unbekannt'
  return date.toLocaleString('de-DE', {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

function getAttachmentLabel(attachment) {
  if (!attachment?.filename) return 'Datei'
  const parts = attachment.filename.split('.')
  const ext = parts.length > 1 ? parts.pop().toUpperCase() : 'FILE'
  return ext || 'FILE'
}

function getAttachmentStatusLabel(attachment) {
  if (attachment?.kind === 'file') {
    return attachment.readStatus === 'error'
      ? 'Lesefehler'
      : attachment.readStatus === 'ready'
        ? 'Datei bereit'
        : 'Liest…'
  }
  return attachment?.ocrStatus === 'ready'
    ? 'OCR prêt'
    : attachment?.ocrStatus === 'error'
      ? 'OCR Fehler'
      : attachment?.ocrStatus === 'empty'
        ? 'OCR leer'
        : 'OCR läuft'
}

function authHeaders(extra = {}) {
  const headers = { ...extra }
  if (state.token) {
    headers.Authorization = `Bearer ${state.token}`
  }
  return headers
}

async function apiJson(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    ...options,
    headers: authHeaders({
      ...(options.headers || {}),
      ...(options.body && !(options.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}),
    }),
  })

  let data = null
  try {
    data = await response.json()
  } catch (error) {
    data = null
  }

  if (!response.ok) {
    const message = data?.detail || data?.error || `HTTP ${response.status}`
    throw new Error(message)
  }

  return data
}

async function apiBlob(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    ...options,
    headers: authHeaders(options.headers || {}),
  })
  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `HTTP ${response.status}`)
  }
  return response
}

async function transcribeAudioBlob(blob) {
  if (!blob || blob.size === 0 || !state.token) return ''

  const formData = new FormData()
  const ext = blob.type?.includes('ogg')
    ? 'ogg'
    : blob.type?.includes('mp4')
      ? 'm4a'
      : 'webm'
  formData.append('file', blob, `voice.${ext}`)

  const response = await fetch(`${API}/audio/transcribe`, {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  })

  let data = null
  try {
    data = await response.json()
  } catch (error) {
    data = null
  }

  if (!response.ok) {
    throw new Error(data?.detail || data?.error || `HTTP ${response.status}`)
  }

  return String(data?.text || '').trim()
}

function showToast(message, type = 'success') {
  const root = document.getElementById('toast-root')
  if (!root) return
  const toast = document.createElement('div')
  toast.className = `toast ${type}`
  toast.textContent = message
  root.appendChild(toast)
  requestAnimationFrame(() => toast.classList.add('show'))
  setTimeout(() => {
    toast.classList.remove('show')
    setTimeout(() => toast.remove(), 220)
  }, 3200)
}

function showLoader(text = 'Bitte warten...') {
  let overlay = document.getElementById('loader-overlay')
  if (!overlay) {
    overlay = document.createElement('div')
    overlay.id = 'loader-overlay'
    overlay.className = 'loader-overlay'
    const card = document.createElement('div')
    card.className = 'loader-card'
    const label = document.createElement('div')
    label.id = 'loader-text'
    card.appendChild(label)
    overlay.appendChild(card)
    document.body.appendChild(overlay)
  }
  const label = document.getElementById('loader-text')
  if (label) label.textContent = text
  overlay.classList.remove('hidden')
}

function hideLoader() {
  const overlay = document.getElementById('loader-overlay')
  if (overlay) overlay.remove()
}

function hideThinkingIndicator() {
  if (state.thinkingMessage) {
    state.thinkingMessage.remove()
    state.thinkingMessage = null
  }
}

function showThinkingIndicator(text = 'Hippo denkt nach…') {
  hideThinkingIndicator()

  const message = document.createElement('article')
  message.className = 'message assistant thinking'

  const bubble = document.createElement('div')
  bubble.className = 'message-bubble'

  const roleTag = document.createElement('div')
  roleTag.className = 'message-role'
  roleTag.textContent = 'Hippo'

  const indicator = document.createElement('div')
  indicator.className = 'thinking-indicator'

  const label = document.createElement('div')
  label.className = 'thinking-label'
  label.textContent = text

  const dots = document.createElement('div')
  dots.className = 'thinking-dots'
  for (let index = 0; index < 3; index += 1) {
    const dot = document.createElement('span')
    dot.className = 'thinking-dot'
    dots.appendChild(dot)
  }

  indicator.append(label, dots)
  bubble.append(roleTag, indicator)
  message.appendChild(bubble)
  els.chatLog.appendChild(message)
  els.chatLog.scrollTop = els.chatLog.scrollHeight
  state.thinkingMessage = message
}

function setScreen(loggedIn) {
  els.loginScreen.classList.toggle('hidden', loggedIn)
  els.workspaceShell.classList.toggle('hidden', !loggedIn)
  if (!loggedIn) {
    closeSidebarDrawer()
  }
}

function isMobileViewport() {
  return window.matchMedia('(max-width: 860px)').matches
}

function setSidebarDrawer(open) {
  els.appShell.classList.toggle('sidebar-open', open)
  if (els.sidebarBackdrop) {
    els.sidebarBackdrop.classList.toggle('visible', open)
  }
  if (els.sidebarToggle) {
    els.sidebarToggle.setAttribute('aria-expanded', String(open))
  }
}

function openSidebarDrawer() {
  if (!isMobileViewport()) return
  setSidebarDrawer(true)
}

function closeSidebarDrawer() {
  setSidebarDrawer(false)
}

function toggleSidebarDrawer() {
  if (!isMobileViewport()) return
  setSidebarDrawer(!els.appShell.classList.contains('sidebar-open'))
}

function updatePresence() {
  if (!state.user) {
    els.accountAvatar.textContent = 'H'
    els.accountName.textContent = 'Nicht verbunden'
    els.accountMeta.textContent = 'Bitte anmelden'
    els.rolePill.textContent = 'Benutzer'
    return
  }

  els.accountAvatar.textContent = initialsFromUser(state.user)
  els.accountName.textContent = state.user.full_name || state.user.email
  els.accountMeta.textContent = state.user.email
  els.rolePill.textContent = formatRole(state.user.role)
}

function renderContext() {
  const project = getContextProject()
  els.projectPill.textContent = project ? project.name : 'Global'
  if (els.projectEmbedBtn) {
    els.projectEmbedBtn.disabled = !project
  }
  if (state.currentConversationId) {
    const conversation = state.conversations.find((item) => item.id === state.currentConversationId)
    els.pageTitle.textContent = getConversationTitle(conversation)
    els.selectedInfo.textContent = project
      ? `Projekt: ${project.name}${project.watched_folder ? ` · Ordner: ${project.watched_folder}` : ''}`
      : 'Globale Unterhaltung'
  } else {
    els.pageTitle.textContent = project ? `Neuer Chat in ${project.name}` : 'Neuer Chat'
    els.selectedInfo.textContent = project
      ? `Projekt: ${project.name}${project.watched_folder ? ` · Ordner: ${project.watched_folder}` : ''}`
      : 'Kein Projekt gewählt'
  }
}

function renderProjects() {
  els.projectList.innerHTML = ''
  els.projectList.appendChild(createProjectCreateCard())

  state.projects.forEach((project) => {
    const active = state.selectedProjectId === project.id
    const row = document.createElement('div')
    row.className = `project-item${active ? ' active' : ''}`
    row.tabIndex = 0
    row.setAttribute('role', 'button')
    row.addEventListener('click', () => selectProject(project.id))
    row.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault()
        selectProject(project.id)
      }
    })

    const icon = document.createElement('div')
    icon.className = 'item-icon'
    icon.textContent = '◌'

    const main = document.createElement('div')
    main.className = 'item-main'
    const title = document.createElement('div')
    title.className = 'item-title'
    title.textContent = project.name
    const subtitle = document.createElement('div')
    subtitle.className = 'item-subtitle'
    subtitle.textContent = project.watched_folder ? project.watched_folder : 'Kein Ordner verknüpft'
    main.append(title, subtitle)

    const chip = document.createElement('div')
    chip.className = 'item-chip'
    const count = state.conversations.filter((conversation) => conversation.project_id === project.id).length
    chip.textContent = `${count} chats`

    const actions = document.createElement('div')
    actions.className = 'item-actions'

    const folderAction = document.createElement('button')
    folderAction.type = 'button'
    folderAction.className = 'item-action-button'
    folderAction.title = 'Projekt bearbeiten'
    folderAction.textContent = '✎'
    folderAction.addEventListener('click', async (event) => {
      event.stopPropagation()
      await openEditProjectModal(project)
    })

    const deleteAction = document.createElement('button')
    deleteAction.type = 'button'
    deleteAction.className = 'item-action-button danger'
    deleteAction.title = 'Projekt löschen'
    deleteAction.textContent = '🗑'
    deleteAction.addEventListener('click', async (event) => {
      event.stopPropagation()
      await deleteProject(project)
    })

    actions.append(folderAction, deleteAction)

    row.append(icon, main, chip, actions)
    els.projectList.appendChild(row)
  })

  q('project-count').textContent = String(state.projects.length)
}

function createProjectCreateCard() {
  const button = document.createElement('button')
  button.type = 'button'
  button.className = 'ghost-action'
  button.textContent = '+ Projekt erstellen'
  button.addEventListener('click', openCreateProjectModal)
  return button
}

function renderConversations() {
  els.conversationList.innerHTML = ''
  const conversations = [...state.conversations].sort((a, b) => new Date(b.created_at) - new Date(a.created_at))

  const allLabel = document.createElement('div')
  allLabel.className = 'section-badge'
  allLabel.style.margin = '0 6px 2px'
  allLabel.textContent = state.selectedProjectId ? 'Chats und Projektkontext' : 'Alle Chats'
  els.conversationList.appendChild(allLabel)

  if (conversations.length === 0) {
    const empty = document.createElement('div')
    empty.className = 'muted-copy'
    empty.style.padding = '8px 6px'
    empty.textContent = 'Noch keine Chats.'
    els.conversationList.appendChild(empty)
  } else {
    conversations.forEach((conversation) => {
      const active = state.currentConversationId === conversation.id
      const row = document.createElement('div')
      row.className = `conversation-item${active ? ' active' : ''}`
      row.tabIndex = 0
      row.setAttribute('role', 'button')
      row.addEventListener('click', () => openConversation(conversation))
      row.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          openConversation(conversation)
        }
      })

      const icon = document.createElement('div')
      icon.className = 'item-icon'
      icon.textContent = '◉'

      const main = document.createElement('div')
      main.className = 'item-main'
      const title = document.createElement('div')
      title.className = 'item-title'
      title.textContent = getConversationTitle(conversation)
      const subtitle = document.createElement('div')
      subtitle.className = 'item-subtitle'
      subtitle.textContent = conversation.created_at ? new Date(conversation.created_at).toLocaleString() : ''
      main.append(title, subtitle)

      const chip = document.createElement('div')
      chip.className = 'item-chip'
      if (conversation.project_id) {
        const project = state.projects.find((item) => item.id === conversation.project_id)
        chip.textContent = project ? project.name : 'Projekt'
      } else {
        chip.textContent = 'Global'
      }

      const actions = document.createElement('div')
      actions.className = 'item-actions'

      const deleteAction = document.createElement('button')
      deleteAction.type = 'button'
      deleteAction.className = 'item-action-button danger'
      deleteAction.title = 'Chat löschen'
      deleteAction.textContent = '🗑'
      deleteAction.addEventListener('click', async (event) => {
        event.stopPropagation()
        await deleteConversation(conversation)
      })

      actions.append(deleteAction)

      row.append(icon, main, chip, actions)
      els.conversationList.appendChild(row)
    })
  }

  q('chat-count').textContent = String(conversations.length)
}

function renderUsers() {}

function renderDashboardUsers(container) {
  if (!container) return
  container.innerHTML = ''

  if (!Array.isArray(state.users) || !state.users.length) {
    const empty = document.createElement('div')
    empty.className = 'muted-copy'
    empty.textContent = 'Noch keine Benutzer geladen.'
    container.appendChild(empty)
    return
  }

  state.users.forEach((user) => {
    const row = document.createElement('div')
    row.className = 'user-item dashboard-user-item'

    const avatar = document.createElement('div')
    avatar.className = 'item-avatar'
    avatar.textContent = initialsFromUser(user)

    const main = document.createElement('div')
    main.className = 'item-main'
    const title = document.createElement('div')
    title.className = 'item-title'
    title.textContent = user.full_name || user.email
    const subtitle = document.createElement('div')
    subtitle.className = 'item-subtitle'
    subtitle.textContent = `${formatRole(user.role)} · ${user.email}`
    main.append(title, subtitle)

    const actions = document.createElement('div')
    actions.className = 'item-actions'

    const deleteButton = document.createElement('button')
    deleteButton.type = 'button'
    deleteButton.className = 'item-action-button danger'
    deleteButton.title = 'Benutzer löschen'
    deleteButton.textContent = '🗑'
    deleteButton.addEventListener('click', async () => {
      await deleteDashboardUser(user)
    })

    actions.append(deleteButton)
    row.append(avatar, main, actions)
    container.appendChild(row)
  })
}

function renderAttachmentPreview() {
  els.attachmentPreview.innerHTML = ''
  state.draftAttachments.forEach((attachment, index) => {
    const pill = document.createElement('div')
    pill.className = 'attachment-pill'

    if (attachment.previewUrl) {
      const previewWrap = document.createElement('div')
      previewWrap.className = 'attachment-thumb-wrap'
      const thumb = document.createElement('img')
      thumb.className = 'attachment-thumb'
      thumb.src = attachment.previewUrl
      thumb.alt = attachment.filename
      const badge = document.createElement('div')
      badge.className = `attachment-badge ${attachment.kind === 'file' ? attachment.readStatus || 'pending' : attachment.ocrStatus || 'pending'}`
      badge.textContent = getAttachmentStatusLabel(attachment)
      previewWrap.append(thumb, badge)
      pill.appendChild(previewWrap)

      const label = document.createElement('div')
      label.className = 'attachment-label'
      label.textContent = attachment.filename
      pill.appendChild(label)
    } else {
      const icon = document.createElement('div')
      icon.className = 'item-avatar'
      icon.textContent = getAttachmentLabel(attachment)
      if (attachment.kind === 'file') {
        icon.classList.add('file-avatar')
      }
      pill.appendChild(icon)

      const label = document.createElement('div')
      label.className = 'attachment-label'
      label.textContent = attachment.filename
      pill.appendChild(label)

        const badge = document.createElement('div')
        badge.className = `attachment-badge ${attachment.kind === 'file' ? attachment.readStatus || 'pending' : attachment.ocrStatus || 'pending'}${attachment.kind === 'file' ? ' file-inline' : ''}`
        badge.textContent = getAttachmentStatusLabel(attachment)
        pill.appendChild(badge)
      }

    const remove = document.createElement('button')
    remove.type = 'button'
    remove.className = 'attachment-remove'
    remove.textContent = '×'
    remove.addEventListener('click', () => {
      state.draftAttachments.splice(index, 1)
      renderAttachmentPreview()
    })
    pill.appendChild(remove)

    els.attachmentPreview.appendChild(pill)
  })
}

function setVoiceIdle() {
  els.voiceStatus.textContent = state.isRecording ? 'Aufnahme läuft...' : 'Mikrofon bereit'
  els.voiceCanvas.classList.toggle('active', state.isRecording)
}

function clearChatLog() {
  els.chatLog.innerHTML = ''
  els.emptyState.classList.remove('hidden')
}

function renderMessage(role, content, extras = {}) {
  els.emptyState.classList.add('hidden')

  const message = document.createElement('article')
  message.className = `message ${role}${extras.attachments?.length ? ' attachments' : ''}`

  const bubble = document.createElement('div')
  bubble.className = 'message-bubble'

  const roleTag = document.createElement('div')
  roleTag.className = 'message-role'
  roleTag.textContent =
    role === 'user' ? 'Du' : role === 'assistant' ? 'Hippo' : role === 'system' ? 'System' : role
  bubble.appendChild(roleTag)

  if (content) {
    const text = document.createElement('div')
    text.className = 'message-text'
    text.appendChild(renderRichContent(content))
    bubble.appendChild(text)
  }

  if (extras.generatedFiles?.length) {
    const artifacts = document.createElement('div')
    artifacts.className = 'generated-artifacts'

    extras.generatedFiles.forEach((artifact) => {
      const card = document.createElement('div')
      card.className = 'generated-artifact-card'

      const previewUrl = artifact?.data_base64 && artifact?.mime_type
        ? `data:${artifact.mime_type};base64,${artifact.data_base64}`
        : ''
      const isImage = artifact?.mime_type?.startsWith('image/')

      if (isImage && previewUrl) {
        const preview = document.createElement('img')
        preview.className = 'generated-artifact-preview'
        preview.src = previewUrl
        preview.alt = artifact.filename || 'Generierte Datei'
        card.appendChild(preview)
      } else {
        const preview = document.createElement('div')
        preview.className = 'generated-artifact-preview generated-artifact-placeholder'
        preview.innerHTML = '<span>FILE</span>'
        card.appendChild(preview)
      }

      const body = document.createElement('div')
      body.className = 'generated-artifact-body'

      const name = document.createElement('div')
      name.className = 'generated-artifact-name'
      name.textContent = artifact.filename || 'Generierte Datei'

      const meta = document.createElement('div')
      meta.className = 'generated-artifact-meta'
      meta.textContent = artifact.mime_type || 'Datei'

      const actions = document.createElement('div')
      actions.className = 'generated-artifact-actions'

      const download = document.createElement('button')
      download.type = 'button'
      download.className = 'item-action-button'
      download.textContent = '↓'
      download.title = 'Datei herunterladen'
      download.addEventListener('click', () => {
        if (!previewUrl) return
        const link = document.createElement('a')
        link.href = previewUrl
        link.download = artifact.filename || 'hippo-datei'
        document.body.appendChild(link)
        link.click()
        link.remove()
      })

      actions.append(download)
      body.append(name, meta, actions)
      card.appendChild(body)
      artifacts.appendChild(card)
    })

    bubble.appendChild(artifacts)
  }

  if (extras.attachments?.length) {
    const wrapper = document.createElement('div')
    wrapper.className = 'message-attachments'
    extras.attachments.forEach((attachment) => {
      if (attachment.previewUrl) {
        const chip = document.createElement('div')
        chip.className = 'image-chip'
        if (attachment.ocrStatus) {
          chip.classList.add(`ocr-${attachment.ocrStatus}`)
        }
        const image = document.createElement('img')
        image.src = attachment.previewUrl
        image.alt = attachment.filename
        const badge = document.createElement('div')
        badge.className = `image-chip-badge ${attachment.ocrStatus || 'pending'}`
        badge.textContent = getAttachmentStatusLabel(attachment)
        const caption = document.createElement('div')
        caption.className = 'caption'
        caption.textContent = attachment.filename
        chip.append(image, badge, caption)
        wrapper.appendChild(chip)
      } else {
        const chip = document.createElement('div')
        chip.className = 'attachment-pill message-file-pill'
        const icon = document.createElement('div')
        icon.className = 'item-avatar file-avatar'
        icon.textContent = getAttachmentLabel(attachment)
        const body = document.createElement('div')
        body.className = 'attachment-file-copy'
        const label = document.createElement('div')
        label.className = 'attachment-label'
        label.textContent = attachment.filename
        const badge = document.createElement('div')
        badge.className = `attachment-badge ${attachment.readStatus || 'pending'} file-inline`
        badge.textContent = getAttachmentStatusLabel(attachment)
        body.append(label, badge)
        chip.append(icon, body)
        wrapper.appendChild(chip)
      }
    })
    bubble.appendChild(wrapper)
  }

  message.appendChild(bubble)
  els.chatLog.appendChild(message)
  els.chatLog.scrollTop = els.chatLog.scrollHeight
}

function renderConversationMessages(messages) {
  els.chatLog.innerHTML = ''
  if (!messages.length) {
    els.emptyState.classList.remove('hidden')
    return
  }

  els.emptyState.classList.add('hidden')
  messages.forEach((message) => renderMessage(message.role, message.content))
}

function resetComposer() {
  state.draftAttachments = []
  els.chatInput.value = ''
  els.chatInput.style.height = 'auto'
  renderAttachmentPreview()
}

function syncSelectedProjectConversation() {
  if (state.selectedProjectId && state.projectConversationMemory.has(state.selectedProjectId)) {
    state.currentConversationId = state.projectConversationMemory.get(state.selectedProjectId)
  }
}

async function loadCurrentUser() {
  const user = await apiJson('/users/me')
  state.user = user
  updatePresence()
  return user
}

async function loadProjects() {
  state.projects = await apiJson('/projects/')
  renderProjects()
  renderContext()
}

async function loadConversations() {
  const conversations = await apiJson('/chat/conversations')
  state.conversations = Array.isArray(conversations) ? conversations : []
  renderConversations()
  renderContext()
}

async function loadUsers() {
  if (state.user?.role !== 'ADMIN') {
    state.users = []
    return
  }
  state.users = await apiJson('/admin/users/')
}

async function loadWorkspace() {
  await Promise.all([loadProjects(), loadConversations(), loadUsers()])
  renderContext()
}

async function login() {
  const email = els.email.value.trim()
  const password = els.password.value
  if (!email || !password) {
    showToast('Please fill email and password.', 'error')
    return
  }

  showLoader('Anmeldung...')
  try {
    const result = await apiJson('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    })
    state.token = result.access_token
    localStorage.setItem('hippo.token', state.token)
    state.user = await loadCurrentUser()
    setScreen(true)
    updatePresence()
    await loadWorkspace()
    showToast('Signed in')
  } catch (error) {
    showToast(error.message || 'Anmeldung fehlgeschlagen', 'error')
    els.loginResult.textContent = error.message || 'Anmeldung fehlgeschlagen'
  } finally {
    hideLoader()
  }
}

function logout() {
  state.token = ''
  state.user = null
  state.projects = []
  state.conversations = []
  state.users = []
  state.selectedProjectId = null
  state.currentConversationId = null
  state.draftAttachments = []
  localStorage.removeItem('hippo.token')
  setScreen(false)
  updatePresence()
  clearChatLog()
  renderProjects()
  renderConversations()
  renderAttachmentPreview()
  renderContext()
}

async function selectProject(projectId) {
  state.selectedProjectId = projectId
  state.currentConversationId = state.projectConversationMemory.get(projectId) || null
  renderProjects()
  renderConversations()
  renderContext()
  closeSidebarDrawer()

  if (state.currentConversationId) {
    await openConversationById(state.currentConversationId)
  } else {
    clearChatLog()
  }
}

async function startNewChat() {
  state.currentConversationId = null
  renderConversations()
  renderContext()
  clearChatLog()
  resetComposer()
  closeSidebarDrawer()
  els.chatInput.focus()
}

async function openConversation(conversation) {
  state.currentConversationId = conversation.id
  if (conversation.project_id) {
    state.selectedProjectId = conversation.project_id
    state.projectConversationMemory.set(conversation.project_id, conversation.id)
  }
  renderProjects()
  renderConversations()
  renderContext()
  closeSidebarDrawer()
  await openConversationById(conversation.id)
}

async function openConversationById(conversationId) {
  showLoader('Unterhaltung wird geladen...')
  try {
    const payload = await apiJson(`/chat/conversations/${conversationId}`)
    renderConversationMessages(payload.messages || [])
  } catch (error) {
    showToast(error.message || 'Failed to load conversation', 'error')
  } finally {
    hideLoader()
  }
}

function resizeComposer() {
  els.chatInput.style.height = 'auto'
  els.chatInput.style.height = `${Math.min(els.chatInput.scrollHeight, 180)}px`
}

function buildImageAttachment(file, dataUrl) {
  return {
    file,
    kind: 'image',
    filename: file.name,
    mime_type: file.type || 'image/*',
    data_url: dataUrl,
    raw_base64: dataUrl.includes(',') ? dataUrl.split(',')[1] : '',
    previewUrl: dataUrl,
    ocr_text: '',
    ocrStatus: 'pending',
    ocrPromise: null,
  }
}

function buildFileAttachment(file, rawBase64) {
  return {
    file,
    kind: 'file',
    filename: file.name,
    mime_type: file.type || 'application/octet-stream',
    raw_base64: rawBase64,
    data_url: null,
    previewUrl: null,
    ocr_text: '',
    readStatus: 'ready',
    ocrPromise: Promise.resolve(''),
  }
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ''))
    reader.onerror = () => reject(reader.error || new Error('Unable to read file'))
    reader.readAsDataURL(file)
  })
}

function readFileAsArrayBuffer(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result)
    reader.onerror = () => reject(reader.error || new Error('Unable to read file'))
    reader.readAsArrayBuffer(file)
  })
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer || [])
  let binary = ''
  const chunkSize = 0x8000
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize))
  }
  return btoa(binary)
}

async function attachImages(files) {
  const imageFiles = [...files].filter((file) => file && file.type && file.type.startsWith('image/'))
  if (!imageFiles.length) {
    showToast('Hier sind nur Bilddateien erlaubt.', 'error')
    return
  }

  for (const file of imageFiles) {
    const dataUrl = await readFileAsDataUrl(file)
    const attachment = buildImageAttachment(file, dataUrl)
    attachment.ocrPromise = (async () => {
      try {
        const result = await window.electron.ocrImage({ dataUrl })
        if (result?.ok && result.text) {
          attachment.ocr_text = result.text
          attachment.ocrStatus = 'ready'
          renderAttachmentPreview()
          return result.text
        }
        attachment.ocrStatus = 'empty'
        renderAttachmentPreview()
      } catch (error) {
        console.warn('OCR failed', error)
        attachment.ocrStatus = 'error'
        renderAttachmentPreview()
      }
      return ''
    })()
    state.draftAttachments.push(attachment)
  }
  renderAttachmentPreview()
}

async function attachFiles(files) {
  const selectedFiles = [...files].filter(Boolean)
  if (!selectedFiles.length) {
    showToast('Bitte mindestens eine Datei auswählen.', 'error')
    return
  }

  for (const file of selectedFiles) {
    if (file.type && file.type.startsWith('image/')) {
      // Keep image handling on the OCR path so screenshots still get text locally.
      // eslint-disable-next-line no-await-in-loop
      await attachImages([file])
      continue
    }

    // Non-image files are sent as bytes so the backend can extract text locally.
    // eslint-disable-next-line no-await-in-loop
    const buffer = await readFileAsArrayBuffer(file)
    const attachment = buildFileAttachment(file, arrayBufferToBase64(buffer))
    state.draftAttachments.push(attachment)
  }

  renderAttachmentPreview()
}

async function persistAttachment(projectId, attachment) {
  if (!projectId || !attachment?.file) return
  const formData = new FormData()
  formData.append('file', attachment.file, attachment.filename)
  try {
    await apiBlob(`/files/projects/${projectId}/upload`, {
      method: 'POST',
      body: formData,
    })
  } catch (error) {
    showToast(`Bild-Upload übersprungen: ${error.message || 'unbekannter Fehler'}`, 'error')
  }
}

function buildProjectForm(defaults = {}) {
  const wrapper = document.createElement('div')
  wrapper.className = 'modal-grid'

  const nameField = document.createElement('label')
  nameField.className = 'field'
  nameField.innerHTML = '<span>Projektname</span>'
  const nameInput = document.createElement('input')
  nameInput.id = 'name'
  nameInput.type = 'text'
  nameInput.className = 'text-input'
  nameInput.placeholder = 'Projekt Apollo'
  nameInput.value = defaults.name || ''
  nameField.appendChild(nameInput)

  const folderField = document.createElement('label')
  folderField.className = 'field'
  folderField.innerHTML = '<span>Gemeinsamer Ordner</span>'
  const folderRow = document.createElement('div')
  folderRow.style.display = 'flex'
  folderRow.style.gap = '10px'
  const folderInput = document.createElement('input')
  folderInput.id = 'folder'
  folderInput.type = 'text'
  folderInput.className = 'text-input'
  folderInput.placeholder = 'Ordner auswählen'
  folderInput.readOnly = true
  folderInput.style.flex = '1'
  folderInput.value = defaults.folder || ''
  const folderButton = document.createElement('button')
  folderButton.type = 'button'
  folderButton.className = 'ghost-action'
  folderButton.textContent = 'Ordner wählen'
  folderButton.addEventListener('click', async () => {
    const selected = await window.electron.selectFolder()
    if (selected) {
      folderInput.value = selected
    }
  })
  folderRow.append(folderInput, folderButton)
  folderField.appendChild(folderRow)

  const hint = document.createElement('div')
  hint.className = 'muted-copy'
  hint.textContent = 'Hier abgelegte Dateien können von Hippo AI analysiert werden. Generierte Dokumente werden ebenfalls in diesem Ordner gespeichert.'

  wrapper.append(nameField, folderField, hint)
  return wrapper
}

async function openCreateProjectModal() {
  const form = buildProjectForm()
  const result = await openModal({
    title: 'Projekt erstellen',
    copy: 'Wähle einen gemeinsamen Ordner über den Dateidialog aus, statt ihn von Hand einzugeben.',
    content: form,
    submitLabel: 'Erstellen',
  })

  if (!result) return

  showLoader('Projekt wird erstellt...')
  try {
    await apiJson('/projects/', {
      method: 'POST',
      body: JSON.stringify({
        name: result.name,
        description: '',
        watched_folder: result.folder || null,
      }),
    })
    await loadWorkspace()
    showToast('Projekt erstellt')
  } catch (error) {
    showToast(error.message || 'Projekt konnte nicht erstellt werden', 'error')
  } finally {
    hideLoader()
  }
}

async function openEditProjectModal(project) {
  if (!project) return

  const form = buildProjectForm({
    name: project.name,
    folder: project.watched_folder || '',
  })

  const result = await openModal({
    title: 'Projekt bearbeiten',
    copy: 'Hier siehst und änderst du den gemeinsamen Ordner des Projekts.',
    content: form,
    submitLabel: 'Speichern',
    extraActions: [
      {
        label: 'Dateien',
        className: 'ghost-action',
        onClick: async ({ close }) => {
          close()
          await openProjectFilesModal(project)
        },
      },
      {
        label: 'Löschen',
        className: 'ghost-action',
        onClick: async ({ close }) => {
          close()
          await deleteProject(project)
        },
      },
    ],
  })

  if (!result) return

  showLoader('Projekt wird gespeichert...')
  try {
    await apiJson(`/projects/${project.id}`, {
      method: 'PATCH',
      body: JSON.stringify({
        name: result.name,
        description: project.description || '',
        watched_folder: result.folder || null,
      }),
    })
    await loadProjects()
    await loadConversations()
    showToast('Projekt gespeichert')
  } catch (error) {
    showToast(error.message || 'Projekt konnte nicht gespeichert werden', 'error')
  } finally {
    hideLoader()
  }
}

async function deleteProject(project) {
  if (!project) return
  const firstOk = window.confirm(`Projekt "${project.name}" wirklich löschen?`)
  if (!firstOk) return
  const secondOk = window.confirm(`Letzte Bestätigung: Das Projekt "${project.name}" wird dauerhaft gelöscht. Fortfahren?`)
  if (!secondOk) return

  showLoader('Projekt wird gelöscht...')
  try {
    await apiJson(`/projects/${project.id}`, { method: 'DELETE' })
    if (state.selectedProjectId === project.id) {
      state.selectedProjectId = null
      state.currentConversationId = null
    }
    state.projectConversationMemory.delete(project.id)
    await loadProjects()
    await loadConversations()
    renderContext()
    clearChatLog()
    showToast('Projekt gelöscht')
  } catch (error) {
    showToast(error.message || 'Projekt konnte nicht gelöscht werden', 'error')
  } finally {
    hideLoader()
  }
}

async function deleteConversation(conversation) {
  if (!conversation) return
  const firstOk = window.confirm(`Chat "${getConversationTitle(conversation)}" wirklich löschen?`)
  if (!firstOk) return
  const secondOk = window.confirm(`Letzte Bestätigung: Der Chat "${getConversationTitle(conversation)}" wird dauerhaft gelöscht. Fortfahren?`)
  if (!secondOk) return

  showLoader('Chat wird gelöscht...')
  try {
    await apiJson(`/chat/conversations/${conversation.id}`, { method: 'DELETE' })
    if (state.currentConversationId === conversation.id) {
      state.currentConversationId = null
      if (state.selectedProjectId) {
        state.projectConversationMemory.delete(state.selectedProjectId)
      }
    }
    await loadConversations()
    renderContext()
    clearChatLog()
    showToast('Chat gelöscht')
  } catch (error) {
    showToast(error.message || 'Chat konnte nicht gelöscht werden', 'error')
  } finally {
    hideLoader()
  }
}

async function openProjectFilesModal(project) {
  if (!project) return
  showLoader('Projektdateien werden geladen...')
  try {
    const wrapper = document.createElement('div')
    wrapper.className = 'modal-grid'
    const summary = document.createElement('div')
    summary.className = 'storage-summary'
    const filesHost = document.createElement('div')
    filesHost.className = 'modal-grid'

    const renderStorage = (storage) => {
      wrapper.innerHTML = ''
      summary.innerHTML = `
        <div class="storage-summary-line"><span>Speicher</span><strong>${escapeHtml(storage.provider || 'local')}</strong></div>
        <div class="storage-summary-line"><span>Bucket</span><strong>${escapeHtml(storage.bucket || 'lokal')}</strong></div>
        <div class="storage-summary-line"><span>Pfad</span><strong>${escapeHtml(storage.key_prefix || project.watched_folder || '—')}</strong></div>
        <div class="storage-summary-line"><span>Ordner</span><strong>${escapeHtml(storage.watched_folder || '—')}</strong></div>
      `
      filesHost.innerHTML = ''

      const files = Array.isArray(storage.files) ? storage.files : []
      if (files.length) {
        files.forEach((file) => {
          const row = document.createElement('div')
          row.className = 'project-file-row'
          const nameBlock = document.createElement('div')
          nameBlock.className = 'item-main'
          const name = document.createElement('div')
          name.className = 'item-title'
          name.textContent = file.filename
          const meta = document.createElement('div')
          meta.className = 'item-subtitle'
          meta.textContent = `${formatFileSize(file.size)} · ${formatDateLabel(file.modified_at)} · ${file.storage || 'local'}`
          nameBlock.append(name, meta)
          const download = document.createElement('button')
          download.type = 'button'
          download.className = 'item-action-button'
          download.textContent = '↓'
          download.title = 'Datei herunterladen'
          download.addEventListener('click', async () => {
            await downloadProjectFile(project, file.filename)
          })

          const remove = document.createElement('button')
          remove.type = 'button'
          remove.className = 'item-action-button danger'
          remove.textContent = '🗑'
          remove.title = 'Datei löschen'
          remove.addEventListener('click', async () => {
            await deleteProjectStorageFile(project, file.filename, refreshModal)
          })

          const actions = document.createElement('div')
          actions.className = 'item-actions'
          actions.append(download, remove)
          row.append(nameBlock, actions)
          filesHost.appendChild(row)
        })
      } else {
        const empty = document.createElement('div')
        empty.className = 'muted-copy'
        empty.textContent = 'Im Projekt-Speicher sind noch keine Dateien sichtbar.'
        filesHost.appendChild(empty)
      }

      wrapper.append(summary, filesHost)
    }

    const refreshModal = async () => {
      const storage = await apiJson(`/files/projects/${project.id}/storage`)
      renderStorage(storage)
    }

    await refreshModal()

    await openModal({
      title: `Dateien · ${project.name}`,
      copy: 'Diese Liste zeigt den verknüpften Projekt-Speicher und die aktuell verfügbaren Dateien.',
      content: wrapper,
      submitLabel: 'Schließen',
      width: 'min(900px, 100%)',
    })
  } catch (error) {
    showToast(error.message || 'Projektdateien konnten nicht geladen werden', 'error')
  } finally {
    hideLoader()
  }
}

async function downloadProjectFile(project, filename) {
  try {
    const response = await apiBlob(`/files/projects/${project.id}/download/${encodeURIComponent(filename)}`)
    const blob = await response.blob()
    const buffer = await blob.arrayBuffer()
    const destinationFolder = project.watched_folder || await window.electron.selectFolder()
    if (!destinationFolder) {
      showToast('Kein Zielordner gewählt.', 'error')
      return
    }
    const base64 = arrayBufferToBase64(buffer)
    const result = await window.electron.saveFile({
      folder: destinationFolder,
      filename,
      data: { base64 },
    })
    if (result?.ok) {
      showToast(`Datei gespeichert: ${result.path}`)
    } else {
      showToast(result?.error || 'Datei konnte nicht gespeichert werden', 'error')
    }
  } catch (error) {
    showToast(error.message || 'Datei konnte nicht heruntergeladen werden', 'error')
  }
}

async function deleteProjectStorageFile(project, filename, refresh) {
  if (!project?.id || !filename) return
  const firstOk = window.confirm(`Datei "${filename}" wirklich löschen?`)
  if (!firstOk) return
  const secondOk = window.confirm(`Letzte Bestätigung: "${filename}" wird dauerhaft aus dem Projekt-Speicher entfernt. Fortfahren?`)
  if (!secondOk) return

  showLoader('Datei wird gelöscht...')
  try {
    await apiJson(`/files/projects/${project.id}/storage/${encodeURIComponent(filename)}`, {
      method: 'DELETE',
    })
    showToast(`Datei gelöscht: ${filename}`)
    if (typeof refresh === 'function') {
      await refresh()
    }
  } catch (error) {
    showToast(error.message || 'Datei konnte nicht gelöscht werden', 'error')
  } finally {
    hideLoader()
  }
}

function buildUserForm(defaults = {}) {
  const wrapper = document.createElement('div')
  wrapper.className = 'modal-grid'

  const fields = [
    { id: 'full_name', label: 'Vollständiger Name', type: 'text', placeholder: 'Jane Doe', value: defaults.full_name || '' },
    { id: 'email', label: 'E-Mail', type: 'email', placeholder: 'name@beispiel.de', value: defaults.email || '' },
    { id: 'password', label: 'Passwort', type: 'password', placeholder: defaults.passwordPlaceholder || 'Mindestens 8 Zeichen', value: '' },
  ]

  fields.forEach((field) => {
    const row = document.createElement('label')
    row.className = 'field'
    const label = document.createElement('span')
    label.textContent = field.label
    const input = document.createElement('input')
    input.id = field.id
    input.type = field.type
    input.placeholder = field.placeholder
    input.className = 'text-input'
    input.value = field.value
    row.append(label, input)
    wrapper.appendChild(row)
  })

  const roleField = document.createElement('label')
  roleField.className = 'field'
  const roleLabel = document.createElement('span')
  roleLabel.textContent = 'Rolle'
  const roleSelect = document.createElement('select')
  roleSelect.id = 'role'
  roleSelect.className = 'text-input'
  const roleLabels = {
    USER: 'Benutzer',
    MANAGER: 'Manager',
    READ_ONLY: 'Nur lesen',
    ADMIN: 'Administrator',
  }
  ;['USER', 'MANAGER', 'READ_ONLY', 'ADMIN'].forEach((role) => {
    const option = document.createElement('option')
    option.value = role
    option.textContent = roleLabels[role]
    if ((defaults.role || 'USER') === role) option.selected = true
    roleSelect.appendChild(option)
  })
  roleField.append(roleLabel, roleSelect)
  wrapper.appendChild(roleField)

  return wrapper
}

async function openCreateUserModal() {
  await openUserDashboardModal('users')
}

function createForm(fields) {
  const wrapper = document.createElement('div')
  wrapper.className = 'modal-grid'

  fields.forEach((field) => {
    const row = document.createElement('label')
    row.className = 'field'
    const label = document.createElement('span')
    label.textContent = field.label
    row.appendChild(label)

    let input
    if (field.type === 'select') {
      input = document.createElement('select')
      input.className = 'text-input'
      field.options.forEach((option) => {
        const optionNode = document.createElement('option')
        optionNode.value = option
        optionNode.textContent = option
        input.appendChild(optionNode)
      })
    } else {
      input = document.createElement('input')
      input.type = field.type
      input.placeholder = field.placeholder || ''
      input.className = 'text-input'
    }
    input.id = field.id
    row.appendChild(input)
    wrapper.appendChild(row)
  })

  return wrapper
}

function buildDashboardUserFields(user) {
  const wrapper = document.createElement('div')
  wrapper.className = 'modal-grid'

  const fields = [
    { id: 'full_name', label: 'Vollständiger Name', type: 'text', value: user.full_name || '' },
    { id: 'email', label: 'E-Mail', type: 'email', value: user.email || '' },
    { id: 'password', label: 'Neues Passwort', type: 'password', placeholder: 'Leer lassen, um es nicht zu ändern' },
  ]

  fields.forEach((field) => {
    const row = document.createElement('label')
    row.className = 'field'
    const label = document.createElement('span')
    label.textContent = field.label
    const input = document.createElement('input')
    input.id = field.id
    input.type = field.type
    input.className = 'text-input'
    input.placeholder = field.placeholder || ''
    input.value = field.value || ''
    row.append(label, input)
    wrapper.appendChild(row)
  })

  return wrapper
}

function buildDashboardCreateUserFields() {
  const wrapper = document.createElement('div')
  wrapper.className = 'modal-grid'

  const fields = [
    { id: 'dashboard-user-name', label: 'Vollständiger Name', type: 'text', placeholder: 'Jane Doe' },
    { id: 'dashboard-user-email', label: 'E-Mail', type: 'email', placeholder: 'name@beispiel.de' },
    { id: 'dashboard-user-password', label: 'Passwort', type: 'password', placeholder: 'Mindestens 8 Zeichen' },
  ]

  fields.forEach((field) => {
    const row = document.createElement('label')
    row.className = 'field'
    const label = document.createElement('span')
    label.textContent = field.label
    const input = document.createElement('input')
    input.id = field.id
    input.type = field.type
    input.placeholder = field.placeholder
    input.className = 'text-input'
    row.append(label, input)
    wrapper.appendChild(row)
  })

  const roleField = document.createElement('label')
  roleField.className = 'field'
  const roleLabel = document.createElement('span')
  roleLabel.textContent = 'Rolle'
  const roleSelect = document.createElement('select')
  roleSelect.id = 'dashboard-user-role'
  roleSelect.className = 'text-input'
  const roleLabels = {
    USER: 'Benutzer',
    MANAGER: 'Manager',
    READ_ONLY: 'Nur lesen',
    ADMIN: 'Administrator',
  }
  ;['USER', 'MANAGER', 'READ_ONLY', 'ADMIN'].forEach((role) => {
    const option = document.createElement('option')
    option.value = role
    option.textContent = roleLabels[role]
    if (role === 'USER') option.selected = true
    roleSelect.appendChild(option)
  })
  roleField.append(roleLabel, roleSelect)
  wrapper.appendChild(roleField)

  return wrapper
}

async function saveDashboardProfile(container) {
  const full_name = container.querySelector('#full_name')?.value.trim() || ''
  const email = container.querySelector('#email')?.value.trim() || ''
  const password = container.querySelector('#password')?.value.trim() || ''

  showLoader('Profil wird gespeichert...')
  try {
    await apiJson('/users/me', {
      method: 'PATCH',
      body: JSON.stringify({
        full_name,
        email,
        password: password || null,
      }),
    })
    state.user = await loadCurrentUser()
    updatePresence()
    showToast('Profil gespeichert')
  } catch (error) {
    showToast(error.message || 'Profil konnte nicht gespeichert werden', 'error')
  } finally {
    hideLoader()
  }
}

async function createDashboardUser(container) {
  const full_name = container.querySelector('#dashboard-user-name')?.value.trim() || ''
  const email = container.querySelector('#dashboard-user-email')?.value.trim() || ''
  const password = container.querySelector('#dashboard-user-password')?.value.trim() || ''
  const role = container.querySelector('#dashboard-user-role')?.value || 'USER'

  if (!full_name || !email || !password) {
    showToast('Bitte Name, E-Mail und Passwort ausfüllen.', 'error')
    return
  }

  showLoader('Benutzer wird erstellt...')
  try {
    await apiJson('/admin/users/', {
      method: 'POST',
      body: JSON.stringify({
        full_name,
        email,
        password,
        role,
      }),
    })
    await loadUsers()
    const dashboardUsersList = document.querySelector('[data-dashboard-users]')
    if (dashboardUsersList) renderDashboardUsers(dashboardUsersList)
    showToast('Benutzer erstellt')
  } catch (error) {
    showToast(error.message || 'Benutzer konnte nicht erstellt werden', 'error')
  } finally {
    hideLoader()
  }
}

async function deleteDashboardUser(user) {
  if (!user?.id) return
  if (state.user?.id === user.id) {
    showToast('Das eigene Konto kann hier nicht gelöscht werden.', 'error')
    return
  }

  const firstOk = window.confirm(`Benutzer "${user.full_name || user.email}" wirklich löschen?`)
  if (!firstOk) return
  const secondOk = window.confirm(`Letzte Bestätigung: Benutzer "${user.full_name || user.email}" wird dauerhaft gelöscht. Fortfahren?`)
  if (!secondOk) return

  showLoader('Benutzer wird gelöscht...')
  try {
    await apiJson(`/admin/users/${user.id}`, {
      method: 'DELETE',
    })
    await loadUsers()
    const dashboardUsersList = document.querySelector('[data-dashboard-users]')
    if (dashboardUsersList) renderDashboardUsers(dashboardUsersList)
    showToast('Benutzer gelöscht')
  } catch (error) {
    showToast(error.message || 'Benutzer konnte nicht gelöscht werden', 'error')
  } finally {
    hideLoader()
  }
}

function renderDashboardProjectFiles(container, storage) {
  const fileList = container.querySelector('[data-project-files]')
  if (!fileList) return
  fileList.innerHTML = ''
  const files = Array.isArray(storage?.files) ? storage.files : []
  if (!files.length) {
    const empty = document.createElement('div')
    empty.className = 'muted-copy'
    empty.textContent = 'Im Bucket sind noch keine Dateien sichtbar.'
    fileList.appendChild(empty)
    return
  }

  files.forEach((file) => {
    const row = document.createElement('div')
    row.className = 'project-file-row'
    const left = document.createElement('div')
    left.className = 'item-main'
    const name = document.createElement('div')
    name.className = 'item-title'
    name.textContent = file.filename
    const meta = document.createElement('div')
    meta.className = 'item-subtitle'
    meta.textContent = `${formatFileSize(file.size)} · ${formatDateLabel(file.modified_at)} · ${file.storage || 'local'}`
    left.append(name, meta)
    const download = document.createElement('button')
    download.type = 'button'
    download.className = 'item-action-button'
    download.textContent = '↓'
    download.title = 'Datei herunterladen'
    download.addEventListener('click', async () => {
      const project = state.projects.find((item) => item.id === storage.project_id)
      if (project) {
        await downloadProjectFile(project, file.filename)
      }
    })

    const remove = document.createElement('button')
    remove.type = 'button'
    remove.className = 'item-action-button danger'
    remove.textContent = '🗑'
    remove.title = 'Datei löschen'
    remove.addEventListener('click', async () => {
      const project = state.projects.find((item) => item.id === storage.project_id)
      if (project) {
        await deleteProjectStorageFile(project, file.filename, () => refreshDashboardStorage(container, storage.project_id))
      }
    })

    const actions = document.createElement('div')
    actions.className = 'item-actions'
    actions.append(download, remove)
    row.append(left, actions)
    fileList.appendChild(row)
  })
}

async function refreshDashboardStorage(container, projectId) {
  const summary = container.querySelector('[data-storage-summary]')
  if (!summary || !projectId) return
  summary.textContent = 'Projektdateien werden geladen...'
  try {
    const storage = await apiJson(`/files/projects/${projectId}/storage`)
    renderDashboardProjectFiles(container, storage)
    summary.innerHTML = `
      <div class="storage-summary-line"><span>Speicher</span><strong>${escapeHtml(storage.provider || 'local')}</strong></div>
      <div class="storage-summary-line"><span>Bucket</span><strong>${escapeHtml(storage.bucket || 'lokal')}</strong></div>
      <div class="storage-summary-line"><span>Pfad</span><strong>${escapeHtml(storage.key_prefix || '—')}</strong></div>
      <div class="storage-summary-line"><span>Ordner</span><strong>${escapeHtml(storage.watched_folder || '—')}</strong></div>
    `
    container.querySelector('[data-upload-btn]').disabled = false
    container.querySelector('[data-upload-input]').dataset.projectId = String(projectId)
  } catch (error) {
    summary.textContent = error.message || 'Projektdateien konnten nicht geladen werden'
  }
}

async function uploadDashboardFiles(container, projectId, fileList) {
  if (!projectId || !fileList?.length) return
  showLoader('Dateien werden hochgeladen...')
  try {
    for (const file of fileList) {
      const formData = new FormData()
      formData.append('file', file, file.name)
      // eslint-disable-next-line no-await-in-loop
      await apiBlob(`/files/projects/${projectId}/upload`, {
        method: 'POST',
        body: formData,
      })
    }
    showToast('Dateien hochgeladen')
    await refreshDashboardStorage(container, projectId)
  } catch (error) {
    showToast(error.message || 'Upload fehlgeschlagen', 'error')
  } finally {
    hideLoader()
  }
}

async function openUserDashboardModal(initialTab = 'profile') {
  if (!state.user) return
  if (state.user.role === 'ADMIN') {
    await loadUsers()
  }

  const wrapper = document.createElement('div')
  wrapper.className = 'dashboard-modal'

  const header = document.createElement('div')
  header.className = 'dashboard-header'
  const headerCopy = document.createElement('div')
  headerCopy.className = 'dashboard-header-copy'
  const headerTitle = document.createElement('div')
  headerTitle.className = 'dashboard-title'
  headerTitle.textContent = 'Benutzer-Dashboard'
  const headerMeta = document.createElement('div')
  headerMeta.className = 'dashboard-meta'
  headerMeta.textContent = 'Profil, Projekt-Speicher und Benutzerverwaltung an einem Ort.'
  headerCopy.append(headerTitle, headerMeta)

  const avatar = document.createElement('div')
  avatar.className = 'dashboard-avatar'
  avatar.textContent = initialsFromUser(state.user)
  header.append(headerCopy, avatar)

  const tabs = document.createElement('div')
  tabs.className = 'dashboard-tabs'
  const tabButtons = new Map()
  const panels = new Map()

  function setActiveTab(tabName) {
    tabButtons.forEach((button, key) => {
      button.classList.toggle('active', key === tabName)
    })
    panels.forEach((panel, key) => {
      panel.classList.toggle('hidden', key !== tabName)
    })
  }

  function createTabButton(name, label) {
    const button = document.createElement('button')
    button.type = 'button'
    button.className = 'dashboard-tab'
    button.textContent = label
    button.addEventListener('click', () => {
      setActiveTab(name)
      if (name === 'storage' && projectSelect.value) {
        refreshDashboardStorage(storagePanel, Number(projectSelect.value))
      }
    })
    tabButtons.set(name, button)
    tabs.appendChild(button)
    return button
  }

  const activeTab = state.user.role === 'ADMIN' && initialTab === 'users'
    ? 'users'
    : initialTab === 'storage' || initialTab === 'profile'
      ? initialTab
      : 'profile'
  createTabButton('profile', 'Profil')
  createTabButton('storage', 'S3 / Dateien')
  if (state.user.role === 'ADMIN') {
    createTabButton('users', 'Benutzer')
  }

  const profilePanel = document.createElement('section')
  profilePanel.className = 'dashboard-panel'
  const profileForm = buildDashboardUserFields(state.user)
  const profileActions = document.createElement('div')
  profileActions.className = 'dashboard-panel-actions'
  const saveProfileBtn = document.createElement('button')
  saveProfileBtn.type = 'button'
  saveProfileBtn.className = 'primary-button'
  saveProfileBtn.textContent = 'Profil speichern'
  saveProfileBtn.addEventListener('click', () => saveDashboardProfile(profilePanel))
  profileActions.appendChild(saveProfileBtn)
  profilePanel.append(profileForm, profileActions)
  panels.set('profile', profilePanel)

  const storagePanel = document.createElement('section')
  storagePanel.className = 'dashboard-panel'
  const projectRow = document.createElement('div')
  projectRow.className = 'dashboard-project-row'
  const projectLabel = document.createElement('label')
  projectLabel.className = 'field'
  const projectLabelText = document.createElement('span')
  projectLabelText.textContent = 'Projekt'
  const projectSelect = document.createElement('select')
  projectSelect.className = 'text-input'
  projectSelect.id = 'dashboard-project-select'
  const projectOptions = state.projects.filter((project) => project && project.id)
  projectOptions.forEach((project) => {
    const option = document.createElement('option')
    option.value = String(project.id)
    option.textContent = project.name
    projectSelect.appendChild(option)
  })
  if (initialTab === 'storage' && state.selectedProjectId) {
    projectSelect.value = String(state.selectedProjectId)
  } else if (state.selectedProjectId) {
    projectSelect.value = String(state.selectedProjectId)
  } else if (projectOptions[0]) {
    projectSelect.value = String(projectOptions[0].id)
  }
  projectLabel.append(projectLabelText, projectSelect)

  const uploadButton = document.createElement('button')
  uploadButton.type = 'button'
  uploadButton.className = 'ghost-action'
  uploadButton.textContent = 'Dateien hochladen'
  uploadButton.dataset.uploadBtn = 'true'

  const clearStorageButton = document.createElement('button')
  clearStorageButton.type = 'button'
  clearStorageButton.className = 'ghost-action'
  clearStorageButton.textContent = 'Speicher leeren'
  clearStorageButton.title = 'Alle Projektdateien löschen'
  clearStorageButton.dataset.clearStorageBtn = 'true'

  const uploadInput = document.createElement('input')
  uploadInput.type = 'file'
  uploadInput.multiple = true
  uploadInput.className = 'hidden'
  uploadInput.dataset.uploadInput = 'true'

  if (!projectOptions.length) {
    projectSelect.disabled = true
    uploadButton.disabled = true
    clearStorageButton.disabled = true
  }

  projectRow.append(projectLabel, uploadButton, clearStorageButton)
  const storageSummary = document.createElement('div')
  storageSummary.className = 'storage-summary'
  storageSummary.dataset.storageSummary = 'true'
  storageSummary.textContent = projectOptions.length ? 'Projektdateien werden geladen...' : 'Kein Projekt ausgewählt.'
  const storageFiles = document.createElement('div')
  storageFiles.className = 'modal-grid'
  storageFiles.dataset.projectFiles = 'true'
  storagePanel.append(projectRow, uploadInput, storageSummary, storageFiles)
  panels.set('storage', storagePanel)

  uploadButton.addEventListener('click', () => {
    const projectId = Number(projectSelect.value)
    if (!projectId) {
      showToast('Wähle zuerst ein Projekt aus.', 'error')
      return
    }
    uploadInput.click()
  })

  clearStorageButton.addEventListener('click', async () => {
    const projectId = Number(projectSelect.value)
    if (!projectId) {
      showToast('Wähle zuerst ein Projekt aus.', 'error')
      return
    }
    const project = state.projects.find((item) => item.id === projectId)
    const projectName = project?.name || `Projekt ${projectId}`
    const firstOk = window.confirm(`Alle Dateien von "${projectName}" wirklich löschen?`)
    if (!firstOk) return
    const secondOk = window.confirm(`Letzte Bestätigung: Der gesamte Projekt-Speicher von "${projectName}" wird gelöscht. Fortfahren?`)
    if (!secondOk) return

    showLoader('Projekt-Speicher wird geleert...')
    try {
      const result = await apiJson(`/files/projects/${projectId}/storage`, {
        method: 'DELETE',
      })
      showToast(`Speicher geleert: ${result.deleted_remote || 0} S3-Dateien, ${result.deleted_local || 0} lokale Dateien`)
      await refreshDashboardStorage(storagePanel, projectId)
    } catch (error) {
      showToast(error.message || 'Speicher konnte nicht geleert werden', 'error')
    } finally {
      hideLoader()
    }
  })

  uploadInput.addEventListener('change', async () => {
    const projectId = Number(projectSelect.value)
    const files = uploadInput.files || []
    if (!projectId || !files.length) return
    await uploadDashboardFiles(storagePanel, projectId, files)
    uploadInput.value = ''
  })

  projectSelect.addEventListener('change', () => {
    const projectId = Number(projectSelect.value)
    if (projectId) {
      refreshDashboardStorage(storagePanel, projectId)
    }
  })

  const usersPanel = document.createElement('section')
  usersPanel.className = 'dashboard-panel'
  if (state.user.role === 'ADMIN') {
    const usersHeader = document.createElement('div')
    usersHeader.className = 'dashboard-panel-header'
    const usersHeaderCopy = document.createElement('div')
    const usersTitle = document.createElement('div')
    usersTitle.className = 'dashboard-panel-title'
    usersTitle.textContent = 'Benutzerverwaltung'
    const usersSubtitle = document.createElement('div')
    usersSubtitle.className = 'dashboard-panel-subtitle'
    usersSubtitle.textContent = 'Alle Benutzer sehen, neue Benutzer anlegen und Rollen prüfen.'
    usersHeaderCopy.append(usersTitle, usersSubtitle)

    const createAction = document.createElement('button')
    createAction.type = 'button'
    createAction.className = 'primary-button dashboard-inline-action'
    createAction.textContent = 'Benutzer erstellen'
    createAction.addEventListener('click', async () => {
      await createDashboardUser(usersPanel)
    })

    const createUserForm = buildDashboardCreateUserFields()
    const usersList = document.createElement('div')
    usersList.className = 'dashboard-user-list'
    usersList.dataset.dashboardUsers = 'true'
    renderDashboardUsers(usersList)

    usersPanel.append(usersHeader, createAction, createUserForm, usersList)
    panels.set('users', usersPanel)
  }

  const panelsWrap = document.createElement('div')
  panelsWrap.className = 'dashboard-panels'
  panelsWrap.append(profilePanel, storagePanel)
  if (state.user.role === 'ADMIN') {
    panelsWrap.append(usersPanel)
  }

  wrapper.append(header, tabs, panelsWrap)

  setActiveTab(activeTab)
  if (activeTab === 'storage' && projectSelect.value) {
    refreshDashboardStorage(storagePanel, Number(projectSelect.value))
  }

  await openModal({
    title: 'Konto',
    copy: 'Verwalte dein Profil, deine Projektdateien und, falls du Admin bist, Benutzer direkt hier.',
    content: wrapper,
    submitLabel: 'Schließen',
    extraActions: [
      {
        label: 'Abmelden',
        className: 'ghost-action',
        onClick: ({ close }) => {
          close()
          logout()
        },
      },
    ],
    width: 'min(980px, 100%)',
  })
}

async function openProfileModal() {
  await openUserDashboardModal('profile')
}

function buildEmbeddingForm(project = null) {
  const wrapper = document.createElement('div')
  wrapper.className = 'modal-grid'

  const textField = document.createElement('label')
  textField.className = 'field'
  const textLabel = document.createElement('span')
  textLabel.textContent = 'Text'
  const textArea = document.createElement('textarea')
  textArea.id = 'text'
  textArea.className = 'composer-input'
  textArea.style.minHeight = '140px'
  textArea.placeholder = 'Hier Informationen eingeben, die ins Embedding gespeichert werden sollen.'
  textField.append(textLabel, textArea)

  const sourceField = document.createElement('label')
  sourceField.className = 'field'
  const sourceLabel = document.createElement('span')
  sourceLabel.textContent = 'Woher stammen die Infos?'
  const sourceInput = document.createElement('select')
  sourceInput.id = 'source'
  sourceInput.className = 'text-input'
  ;[
    ['project-note', 'Eigene Notiz oder Wissen'],
    ['project-file', 'Aus einer Datei im Projektordner'],
    ['meeting', 'Besprechung / Protokoll'],
    ['external', 'Externe Quelle'],
    ['manual', 'Manuell eingegeben'],
  ].forEach(([value, label]) => {
    const option = document.createElement('option')
    option.value = value
    option.textContent = label
    sourceInput.appendChild(option)
  })
  const sourceHelp = document.createElement('div')
  sourceHelp.className = 'muted-copy'
  sourceHelp.textContent = 'Das hilft Hippo zu verstehen, ob der Inhalt aus einem Dokument, einer Notiz oder einer externen Quelle stammt.'
  sourceField.append(sourceLabel, sourceInput, sourceHelp)

  const typeField = document.createElement('label')
  typeField.className = 'field'
  const typeLabel = document.createElement('span')
  typeLabel.textContent = 'Was ist das für Inhalt?'
  const typeInput = document.createElement('select')
  typeInput.id = 'type'
  typeInput.className = 'text-input'
  ;[
    ['document', 'Dokument / Bericht'],
    ['image', 'Bild / Grafik'],
    ['note', 'Notiz / Freitext'],
    ['table', 'Tabelle / Liste'],
    ['instruction', 'Anleitung / Vorgehen'],
  ].forEach(([value, label]) => {
    const option = document.createElement('option')
    option.value = value
    option.textContent = label
    typeInput.appendChild(option)
  })
  const typeHelp = document.createElement('div')
  typeHelp.className = 'muted-copy'
  typeHelp.textContent = 'Wenn du unsicher bist, nimm einfach "Dokument / Bericht" oder "Notiz / Freitext".'
  typeField.append(typeLabel, typeInput, typeHelp)

  const hint = document.createElement('div')
  hint.className = 'muted-copy'
  hint.textContent = project ? `Projekt-ID: ${project.id}` : 'Wähle zuerst ein Projekt.'

  wrapper.append(textField, sourceField, typeField, hint)
  return wrapper
}

async function openEmbeddingModal() {
  const project = getContextProject()
  if (!project) {
    showToast('Wähle zuerst ein Projekt aus.', 'error')
    return
  }

  const form = buildEmbeddingForm(project)
  const result = await openModal({
    title: 'In Embedding speichern',
    copy: 'Diese Information wird im Embedding-Store des aktuellen Projekts abgelegt.',
    content: form,
    submitLabel: 'Speichern',
  })

  if (!result) return

  showLoader('Embedding wird aktualisiert...')
  try {
    await apiJson('/embeddings-proxy/store', {
      method: 'POST',
      body: JSON.stringify({
        project_id: project.id,
        items: [
          {
            text: result.text,
            metadata: {
              source: result.source || 'desktop',
              type: result.type || 'note',
            },
          },
        ],
      }),
    })
    showToast('Informationen ins Embedding gespeichert')
  } catch (error) {
    showToast(error.message || 'Embedding konnte nicht gespeichert werden', 'error')
  } finally {
    hideLoader()
  }
}

function openModal({ title, copy, content, submitLabel, extraActions = [], width = 'min(520px, 100%)' }) {
  return new Promise((resolve) => {
    const overlay = document.createElement('div')
    overlay.className = 'modal-overlay'

    const card = document.createElement('div')
    card.className = 'modal-card'
    card.style.width = width

    const heading = document.createElement('h3')
    heading.textContent = title
    const copyNode = document.createElement('div')
    copyNode.className = 'modal-copy'
    copyNode.textContent = copy

    const body = document.createElement('div')
    body.className = 'modal-body'
    body.appendChild(content)

    const actions = document.createElement('div')
    actions.className = 'modal-actions'

    const cancel = document.createElement('button')
    cancel.type = 'button'
    cancel.className = 'ghost-action'
    cancel.textContent = 'Abbrechen'

    const confirm = document.createElement('button')
    confirm.type = 'button'
    confirm.className = 'primary-button'
    confirm.style.width = 'auto'
    confirm.textContent = submitLabel

    cancel.addEventListener('click', () => {
      overlay.remove()
      resolve(null)
    })

    confirm.addEventListener('click', () => {
      const values = {}
      const inputs = content.querySelectorAll('input, select, textarea')
      inputs.forEach((input) => {
        values[input.id] = input.value.trim()
      })
      overlay.remove()
      resolve(values)
    })

    overlay.addEventListener('click', (event) => {
      if (event.target === overlay) {
        overlay.remove()
        resolve(null)
      }
    })

    extraActions.forEach((actionConfig) => {
      const action = document.createElement('button')
      action.type = 'button'
      action.className = actionConfig.className || 'ghost-action'
      action.textContent = actionConfig.label
      action.addEventListener('click', () => actionConfig.onClick({ close: () => {
        overlay.remove()
        resolve(null)
      } }))
      actions.appendChild(action)
    })
    actions.append(cancel, confirm)
    card.append(heading, copyNode, body, actions)
    overlay.appendChild(card)
    document.body.appendChild(overlay)

    const firstInput = content.querySelector('input, select, textarea')
    if (firstInput) {
      firstInput.focus()
    }
  })
}

function showGeneratedFile(message, projectFolder) {
  const fileMatch = message.match(/<<<FILE:([^>]+)>>>\s*([\s\S]*?)\s*<<<END_FILE>>>/m)
  if (!fileMatch) return false

  if (!projectFolder) {
    showToast('Wähle zuerst ein Projekt mit zugeordnetem Ordner aus.', 'error')
    return true
  }

  const filename = fileMatch[1].trim()
  const content = fileMatch[2]
  showLoader('Datei wird gespeichert...')
  window.electron.saveFile({ folder: projectFolder, filename, data: content })
    .then((result) => {
      hideLoader()
      if (result?.ok) {
        showToast(`Datei erstellt: ${result.path}`)
        renderMessage('system', `Datei erstellt: ${result.path}`)
      } else {
        showToast(result?.error || 'Datei konnte nicht gespeichert werden', 'error')
      }
    })
    .catch((error) => {
      hideLoader()
      showToast(error.message || 'Datei konnte nicht gespeichert werden', 'error')
    })

  return true
}

async function saveGeneratedArtifacts(artifacts, projectFolder) {
  if (!Array.isArray(artifacts) || !artifacts.length) return []
  if (!projectFolder) return []

  const saved = []
  for (const artifact of artifacts) {
    if (!artifact?.filename || !artifact?.data_base64) continue
    // Save the binary payload that the backend prepared for this file.
    // The shared folder lives on the desktop machine, so Electron writes it locally.
    // eslint-disable-next-line no-await-in-loop
    const result = await window.electron.saveFile({
      folder: projectFolder,
      filename: artifact.filename,
      data: { base64: artifact.data_base64 },
    })
    if (result?.ok) {
      saved.push(result.path)
    } else {
      showToast(result?.error || `Datei konnte nicht gespeichert werden: ${artifact.filename}`, 'error')
    }
  }

  if (saved.length) {
    showToast(`Dateien erstellt: ${saved.join(', ')}`)
  }

  return saved
}

async function sendChat() {
  const message = els.chatInput.value.trim()
  if (!message && state.draftAttachments.length === 0) return

  const project = getContextProject()
  await Promise.all(
    state.draftAttachments
      .map((attachment) => attachment.ocrPromise)
      .filter(Boolean)
  )
  const attachments = state.draftAttachments.map((attachment) => ({
    filename: attachment.filename,
    mime_type: attachment.mime_type,
    data_url: attachment.data_url,
    raw_base64: attachment.raw_base64 || '',
    ocr_text: attachment.ocr_text || '',
  }))

  if (project && state.draftAttachments.length) {
    await Promise.all(state.draftAttachments.map((attachment) => persistAttachment(project.id, attachment)))
  }

  renderMessage('user', message || 'Anhang', { attachments: state.draftAttachments })
  resetComposer()

  showThinkingIndicator('Hippo denkt nach…')
  try {
    const response = await apiJson('/chat-enhanced/', {
      method: 'POST',
      body: JSON.stringify({
        conversation_id: state.currentConversationId,
        project_id: state.selectedProjectId,
        message,
        attachments,
      }),
    })

    if (response?.conversation_id) {
      state.currentConversationId = response.conversation_id
      if (state.selectedProjectId) {
        state.projectConversationMemory.set(state.selectedProjectId, response.conversation_id)
      }
      const title = deriveConversationTitle(message, state.draftAttachments)
      state.conversations = state.conversations.map((conversation) => (
        conversation.id === response.conversation_id
          ? { ...conversation, title: conversation.title || title }
          : conversation
      ))
    }

    await loadConversations()
    renderContext()

    const savedArtifacts = await saveGeneratedArtifacts(response.generated_files, project?.watched_folder || null)
    if (response.reply) {
      renderMessage('assistant', response.reply, { generatedFiles: response.generated_files })
    } else if (response.generated_files?.length) {
      renderMessage('assistant', 'Datei wurde erstellt.', { generatedFiles: response.generated_files })
    } else {
      const legacySaved = showGeneratedFile(response.reply || '', project?.watched_folder || null)
      if (legacySaved) return
    }
  } catch (error) {
    showToast(error.message || 'Chat fehlgeschlagen', 'error')
  } finally {
    hideThinkingIndicator()
  }
}

function drawVoiceFrame() {
  if (!state.isRecording || !state.recording?.analyser || !els.voiceCanvas) return

  const canvas = els.voiceCanvas
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const { analyser } = state.recording
  const buffer = new Uint8Array(analyser.frequencyBinCount)
  analyser.getByteFrequencyData(buffer)

  ctx.clearRect(0, 0, canvas.width, canvas.height)
  const barCount = 44
  const step = Math.max(1, Math.floor(buffer.length / barCount))
  const barWidth = canvas.width / barCount

  for (let index = 0; index < barCount; index += 1) {
    const value = buffer[index * step] || 0
    const height = Math.max(8, (value / 255) * canvas.height * 0.82)
    const x = index * barWidth + 4
    const y = (canvas.height - height) / 2
    const radius = 8

    ctx.fillStyle = index % 2 === 0 ? 'rgba(99, 215, 191, 0.92)' : 'rgba(154, 178, 255, 0.82)'
    roundRect(ctx, x, y, Math.max(4, barWidth - 8), height, radius)
    ctx.fill()
  }

  state.recording.rafId = requestAnimationFrame(drawVoiceFrame)
}

function roundRect(ctx, x, y, width, height, radius) {
  const r = Math.min(radius, width / 2, height / 2)
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.lineTo(x + width - r, y)
  ctx.quadraticCurveTo(x + width, y, x + width, y + r)
  ctx.lineTo(x + width, y + height - r)
  ctx.quadraticCurveTo(x + width, y + height, x + width - r, y + height)
  ctx.lineTo(x + r, y + height)
  ctx.quadraticCurveTo(x, y + height, x, y + height - r)
  ctx.lineTo(x, y + r)
  ctx.quadraticCurveTo(x, y, x + r, y)
  ctx.closePath()
}

function stopRecordingUI() {
  state.isRecording = false
  els.micBtn.textContent = '🎙'
  setVoiceIdle()
  if (state.recording?.rafId) {
    cancelAnimationFrame(state.recording.rafId)
  }
  const ctx = els.voiceCanvas.getContext('2d')
  if (ctx) {
    ctx.clearRect(0, 0, els.voiceCanvas.width, els.voiceCanvas.height)
  }
}

async function stopRecording() {
  if (!state.isRecording || !state.recording) return

  const { mediaRecorder, recognition, stream, audioContext } = state.recording
  state.recording.stopping = true

  try {
    if (recognition) recognition.stop()
  } catch (error) {
    console.warn(error)
  }

  try {
    if (mediaRecorder && mediaRecorder.state !== 'inactive') mediaRecorder.stop()
  } catch (error) {
    console.warn(error)
  }

  try {
    stream.getTracks().forEach((track) => track.stop())
  } catch (error) {
    console.warn(error)
  }

  try {
    if (audioContext?.state !== 'closed') await audioContext.close()
  } catch (error) {
    console.warn(error)
  }

  stopRecordingUI()
}

async function startRecording() {
  if (state.isRecording) return

  if (!navigator.mediaDevices?.getUserMedia) {
    showToast('Der Mikrofonzugriff ist in dieser App-Umgebung nicht verfügbar.', 'error')
    return
  }

  try {
    const devices = await navigator.mediaDevices.enumerateDevices().catch(() => [])
    const audioInputs = devices.filter((device) => device.kind === 'audioinput')
    const audioConstraints = audioInputs[0]?.deviceId
      ? {
          deviceId: { exact: audioInputs[0].deviceId },
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        }
      : {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        }

    const stream = await navigator.mediaDevices.getUserMedia({ audio: audioConstraints })
    const audioContext = new (window.AudioContext || window.webkitAudioContext)()
    const analyser = audioContext.createAnalyser()
    analyser.fftSize = 1024
    const source = audioContext.createMediaStreamSource(stream)
    source.connect(analyser)

    const chunks = []
    const mediaRecorder = new MediaRecorder(stream)

    state.recording = {
      stream,
      audioContext,
      analyser,
      mediaRecorder,
      chunks,
      rafId: null,
    }
    state.isRecording = true
    els.micBtn.textContent = '⏹'
    els.voiceStatus.textContent = 'Aufnahme läuft...'
    els.voiceCanvas.classList.add('active')

    mediaRecorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) chunks.push(event.data)
    }

    mediaRecorder.onstop = async () => {
      state.recording = null
      stopRecordingUI()

      if (chunks.length) {
        try {
          els.voiceStatus.textContent = 'Audio wird transkribiert...'
          const audioBlob = new Blob(chunks, { type: mediaRecorder.mimeType || 'audio/webm' })
          const serverTranscript = await transcribeAudioBlob(audioBlob)
          if (serverTranscript) {
            els.chatInput.value = serverTranscript
            resizeComposer()
            els.chatInput.focus()
            showToast('Audio wurde transkribiert und ins Eingabefeld übernommen')
            return
          }
          showToast('Während der Aufnahme wurde kein Text erkannt.', 'error')
          return
        } catch (error) {
          console.warn('Server transcription failed', error)
          showToast(String(error?.message || error || 'Transkription fehlgeschlagen'), 'error')
          return
        }
      }
      showToast('Während der Aufnahme wurde kein Text erkannt.', 'error')
    }

    mediaRecorder.start()
    drawVoiceFrame()
  } catch (error) {
    const message = String(error?.message || error || '')
    if (/requested device not found|notfounderror/i.test(message)) {
      showToast('Kein Mikrofon gefunden oder das Standard-Mikrofon ist nicht erreichbar. Bitte ein anderes Eingabegerät wählen.', 'error')
    } else if (/notallowederror|permission denied|denied/i.test(message)) {
      showToast('Mikrofonzugriff wurde verweigert. Bitte die Berechtigung in der App erlauben.', 'error')
    } else if (/no audio input|no microphone/i.test(message)) {
      showToast('Kein Mikrofon gefunden. Bitte ein anderes Eingabegerät wählen.', 'error')
    } else if (/not allowed|permission/i.test(message)) {
      showToast('Mikrofonzugriff wurde verweigert. Bitte die Berechtigung in der App erlauben.', 'error')
    } else {
      showToast(message || 'Mikrofonzugriff verweigert', 'error')
    }
    stopRecordingUI()
  }
}

function bindComposerEvents() {
  els.chatForm?.addEventListener('submit', (event) => {
    event.preventDefault()
    sendChat()
  })
  els.chatInput.addEventListener('input', resizeComposer)
  els.chatInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      if (els.chatForm?.requestSubmit) {
        els.chatForm.requestSubmit()
      } else {
        sendChat()
      }
    }
  })

  els.attachImageBtn.addEventListener('click', () => {
    els.imageInput.click()
  })

  els.attachFileBtn.addEventListener('click', () => {
    els.fileInput.click()
  })

  els.imageInput.addEventListener('change', async () => {
    const files = els.imageInput.files || []
    if (!files.length) return
    try {
      await attachImages(files)
    } finally {
      els.imageInput.value = ''
    }
  })

  els.fileInput.addEventListener('change', async () => {
    const files = els.fileInput.files || []
    if (!files.length) return
    try {
      await attachFiles(files)
    } finally {
      els.fileInput.value = ''
    }
  })

  els.micBtn.addEventListener('click', async () => {
    if (state.isRecording) {
      await stopRecording()
    } else {
      await startRecording()
    }
  })

  els.sendChat.addEventListener('click', sendChat)
}

function bindSidebarEvents() {
  els.sidebarNewChat.addEventListener('click', startNewChat)
  els.sidebarToggle?.addEventListener('click', toggleSidebarDrawer)
  els.sidebarBackdrop?.addEventListener('click', closeSidebarDrawer)
  els.projectEmbedBtn.addEventListener('click', openEmbeddingModal)
  els.profileBtn.addEventListener('click', openProfileModal)
  els.logoutBtn.addEventListener('click', logout)
}

function bindAuthEvents() {
  const loginForm = document.getElementById('login-form')
  loginForm?.addEventListener('submit', (event) => {
    event.preventDefault()
    login()
  })
}

async function bootstrap() {
  bindAuthEvents()
  bindSidebarEvents()
  bindComposerEvents()
  window.addEventListener('resize', () => {
    if (!isMobileViewport()) {
      closeSidebarDrawer()
    }
  })
  renderProjects()
  renderConversations()
  renderAttachmentPreview()
  setVoiceIdle()

  if (!state.token) {
    setScreen(false)
    updatePresence()
    renderContext()
    return
  }

  try {
    state.user = await loadCurrentUser()
    setScreen(true)
    updatePresence()
    await loadWorkspace()
    if (!state.currentConversationId) {
      clearChatLog()
    }
  } catch (error) {
    console.warn(error)
    logout()
  }
}

bootstrap()

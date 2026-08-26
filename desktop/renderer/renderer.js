const API = 'http://localhost:8000/api/v1'

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
}

const els = {
  appShell: document.getElementById('app-shell'),
  loginScreen: document.getElementById('login-screen'),
  workspaceShell: document.getElementById('workspace-shell'),
  loginButton: document.getElementById('login'),
  email: document.getElementById('email'),
  password: document.getElementById('password'),
  loginResult: document.getElementById('login-result'),
  sidebarNewChat: document.getElementById('sidebar-new-chat'),
  projectList: document.getElementById('project-list'),
  conversationList: document.getElementById('conversation-list'),
  adminSection: document.getElementById('admin-section'),
  adminCreateUser: document.getElementById('admin-create-user'),
  adminUserList: document.getElementById('admin-user-list'),
  accountAvatar: document.getElementById('account-avatar'),
  accountName: document.getElementById('account-name'),
  accountMeta: document.getElementById('account-meta'),
  logoutBtn: document.getElementById('logout-btn'),
  pageTitle: document.getElementById('page-title'),
  selectedInfo: document.getElementById('selected-info'),
  projectPill: document.getElementById('project-pill'),
  rolePill: document.getElementById('role-pill'),
  chatLog: document.getElementById('chat-log'),
  emptyState: document.getElementById('empty-state'),
  attachmentPreview: document.getElementById('attachment-preview'),
  chatInput: document.getElementById('chat-input'),
  attachImageBtn: document.getElementById('attach-image-btn'),
  imageInput: document.getElementById('image-input'),
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

function initialsFromUser(user) {
  const source = (user?.full_name || user?.email || 'H').trim()
  const parts = source.split(/\s+/).filter(Boolean)
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()
  return source.slice(0, 2).toUpperCase()
}

function getContextProject() {
  return state.projects.find((project) => project.id === state.selectedProjectId) || null
}

function getConversationTitle(conversation) {
  if (!conversation) return 'New chat'
  return conversation.title || `Chat #${conversation.id}`
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

function showLoader(text = 'Working...') {
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

function setScreen(loggedIn) {
  els.appShell.classList.toggle('hidden', !loggedIn)
  els.loginScreen.classList.toggle('hidden', loggedIn)
  els.workspaceShell.classList.toggle('hidden', !loggedIn)
}

function updatePresence() {
  if (!state.user) {
    els.accountAvatar.textContent = 'H'
    els.accountName.textContent = 'Not connected'
    els.accountMeta.textContent = 'Sign in to continue'
    els.rolePill.textContent = 'User'
    return
  }

  els.accountAvatar.textContent = initialsFromUser(state.user)
  els.accountName.textContent = state.user.full_name || state.user.email
  els.accountMeta.textContent = state.user.email
  els.rolePill.textContent = state.user.role
  els.adminSection.classList.toggle('hidden', state.user.role !== 'ADMIN')
}

function renderContext() {
  const project = getContextProject()
  els.projectPill.textContent = project ? project.name : 'Global'
  if (state.currentConversationId) {
    const conversation = state.conversations.find((item) => item.id === state.currentConversationId)
    els.pageTitle.textContent = getConversationTitle(conversation)
    els.selectedInfo.textContent = project ? `Project: ${project.name}` : 'Global conversation'
  } else {
    els.pageTitle.textContent = project ? `New chat in ${project.name}` : 'New chat'
    els.selectedInfo.textContent = project ? `Project: ${project.name}` : 'No project selected'
  }
}

function renderProjects() {
  els.projectList.innerHTML = ''
  els.projectList.appendChild(createProjectCreateCard())

  state.projects.forEach((project) => {
    const active = state.selectedProjectId === project.id
    const row = document.createElement('button')
    row.type = 'button'
    row.className = `project-item${active ? ' active' : ''}`
    row.addEventListener('click', () => selectProject(project.id))

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
    subtitle.textContent = project.watched_folder ? project.watched_folder : 'No folder attached'
    main.append(title, subtitle)

    const chip = document.createElement('div')
    chip.className = 'item-chip'
    const count = state.conversations.filter((conversation) => conversation.project_id === project.id).length
    chip.textContent = `${count} chats`

    row.append(icon, main, chip)
    els.projectList.appendChild(row)
  })

  q('project-count').textContent = String(state.projects.length)
}

function createProjectCreateCard() {
  const button = document.createElement('button')
  button.type = 'button'
  button.className = 'ghost-action'
  button.textContent = '+ Create project'
  button.addEventListener('click', openCreateProjectModal)
  return button
}

function renderConversations() {
  els.conversationList.innerHTML = ''
  const conversations = [...state.conversations].sort((a, b) => new Date(b.created_at) - new Date(a.created_at))

  const allLabel = document.createElement('div')
  allLabel.className = 'section-badge'
  allLabel.style.margin = '0 6px 2px'
  allLabel.textContent = state.selectedProjectId ? 'Chats and project context' : 'All chats'
  els.conversationList.appendChild(allLabel)

  if (conversations.length === 0) {
    const empty = document.createElement('div')
    empty.className = 'muted-copy'
    empty.style.padding = '8px 6px'
    empty.textContent = 'No chats yet.'
    els.conversationList.appendChild(empty)
  } else {
    conversations.forEach((conversation) => {
      const active = state.currentConversationId === conversation.id
      const row = document.createElement('button')
      row.type = 'button'
      row.className = `conversation-item${active ? ' active' : ''}`
      row.addEventListener('click', () => openConversation(conversation))

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
        chip.textContent = project ? project.name : 'project'
      } else {
        chip.textContent = 'global'
      }

      row.append(icon, main, chip)
      els.conversationList.appendChild(row)
    })
  }

  q('chat-count').textContent = String(conversations.length)
}

function renderUsers() {
  els.adminUserList.innerHTML = ''
  if (state.user?.role !== 'ADMIN') return

  state.users.slice(0, 8).forEach((user) => {
    const row = document.createElement('div')
    row.className = 'user-item'

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
    subtitle.textContent = user.role
    main.append(title, subtitle)

    const chip = document.createElement('div')
    chip.className = 'item-chip'
    chip.textContent = user.is_active ? 'active' : 'disabled'

    row.append(avatar, main, chip)
    els.adminUserList.appendChild(row)
  })
}

function renderAttachmentPreview() {
  els.attachmentPreview.innerHTML = ''
  state.draftAttachments.forEach((attachment, index) => {
    const pill = document.createElement('div')
    pill.className = 'attachment-pill'

    if (attachment.previewUrl) {
      const thumb = document.createElement('img')
      thumb.className = 'attachment-thumb'
      thumb.src = attachment.previewUrl
      thumb.alt = attachment.filename
      pill.appendChild(thumb)
    } else {
      const icon = document.createElement('div')
      icon.className = 'item-avatar'
      icon.textContent = 'IMG'
      pill.appendChild(icon)
    }

    const label = document.createElement('div')
    label.className = 'attachment-label'
    label.textContent = attachment.filename
    pill.appendChild(label)

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
  els.voiceStatus.textContent = state.isRecording ? 'Recording...' : 'Mic idle'
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
    role === 'user' ? 'You' : role === 'assistant' ? 'Hippo' : role === 'system' ? 'System' : role
  bubble.appendChild(roleTag)

  if (content) {
    const text = document.createElement('div')
    text.className = 'message-text'
    text.textContent = content
    bubble.appendChild(text)
  }

  if (extras.attachments?.length) {
    const wrapper = document.createElement('div')
    wrapper.className = 'message-attachments'
    extras.attachments.forEach((attachment) => {
      if (attachment.previewUrl) {
        const chip = document.createElement('div')
        chip.className = 'image-chip'
        const image = document.createElement('img')
        image.src = attachment.previewUrl
        image.alt = attachment.filename
        const caption = document.createElement('div')
        caption.className = 'caption'
        caption.textContent = attachment.filename
        chip.append(image, caption)
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
    renderUsers()
    return
  }
  state.users = await apiJson('/admin/users/')
  renderUsers()
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

  showLoader('Signing in...')
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
    showToast(error.message || 'Login failed', 'error')
    els.loginResult.textContent = error.message || 'Login failed'
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
  renderUsers()
  renderAttachmentPreview()
  renderContext()
}

async function selectProject(projectId) {
  state.selectedProjectId = projectId
  state.currentConversationId = state.projectConversationMemory.get(projectId) || null
  renderProjects()
  renderConversations()
  renderContext()

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
  await openConversationById(conversation.id)
}

async function openConversationById(conversationId) {
  showLoader('Loading conversation...')
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
    filename: file.name,
    mime_type: file.type || 'image/*',
    data_url: dataUrl,
    previewUrl: dataUrl,
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

async function attachImages(files) {
  const imageFiles = [...files].filter((file) => file && file.type && file.type.startsWith('image/'))
  if (!imageFiles.length) {
    showToast('Only image files are supported here.', 'error')
    return
  }

  for (const file of imageFiles) {
    const dataUrl = await readFileAsDataUrl(file)
    state.draftAttachments.push(buildImageAttachment(file, dataUrl))
  }
  renderAttachmentPreview()
}

async function persistImageAttachment(projectId, attachment) {
  if (!projectId || !attachment?.file) return
  const formData = new FormData()
  formData.append('file', attachment.file, attachment.filename)
  try {
    await apiBlob(`/files/projects/${projectId}/upload`, {
      method: 'POST',
      body: formData,
    })
  } catch (error) {
    showToast(`Image upload skipped: ${error.message || 'unknown error'}`, 'error')
  }
}

async function openCreateProjectModal() {
  const form = createForm([
    { id: 'name', label: 'Project name', type: 'text', placeholder: 'Project Apollo' },
    { id: 'folder', label: 'Watched folder', type: 'text', placeholder: '/path/to/shared/folder' },
  ])

  const result = await openModal({
    title: 'Create project',
    copy: 'Create a project and link a shared folder if you want file generation to save output there.',
    content: form,
    submitLabel: 'Create',
  })

  if (!result) return

  showLoader('Creating project...')
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
    showToast('Project created')
  } catch (error) {
    showToast(error.message || 'Project creation failed', 'error')
  } finally {
    hideLoader()
  }
}

async function openCreateUserModal() {
  const form = createForm([
    { id: 'full_name', label: 'Full name', type: 'text', placeholder: 'Jane Doe' },
    { id: 'email', label: 'Email', type: 'email', placeholder: 'jane@example.com' },
    { id: 'password', label: 'Password', type: 'password', placeholder: 'At least 8 characters' },
    {
      id: 'role',
      label: 'Role',
      type: 'select',
      options: ['USER', 'MANAGER', 'READ_ONLY', 'ADMIN'],
    },
  ])

  const result = await openModal({
    title: 'Create user',
    copy: 'Admin only. Create a new account directly from the workspace.',
    content: form,
    submitLabel: 'Create user',
  })

  if (!result) return

  showLoader('Creating user...')
  try {
    await apiJson('/admin/users/', {
      method: 'POST',
      body: JSON.stringify({
        full_name: result.full_name,
        email: result.email,
        password: result.password,
        role: result.role,
      }),
    })
    await loadUsers()
    showToast('User created')
  } catch (error) {
    showToast(error.message || 'User creation failed', 'error')
  } finally {
    hideLoader()
  }
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

function openModal({ title, copy, content, submitLabel }) {
  return new Promise((resolve) => {
    const overlay = document.createElement('div')
    overlay.className = 'modal-overlay'

    const card = document.createElement('div')
    card.className = 'modal-card'

    const heading = document.createElement('h3')
    heading.textContent = title
    const copyNode = document.createElement('div')
    copyNode.className = 'modal-copy'
    copyNode.textContent = copy

    const actions = document.createElement('div')
    actions.className = 'modal-actions'

    const cancel = document.createElement('button')
    cancel.type = 'button'
    cancel.className = 'ghost-action'
    cancel.textContent = 'Cancel'

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

    actions.append(cancel, confirm)
    card.append(heading, copyNode, content, actions)
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
    showToast('Select a project with a watched folder first.', 'error')
    return true
  }

  const filename = fileMatch[1].trim()
  const content = fileMatch[2]
  showLoader('Saving file...')
  window.electron.saveFile({ folder: projectFolder, filename, data: content })
    .then((result) => {
      hideLoader()
      if (result?.ok) {
        showToast(`File created: ${result.path}`)
        renderMessage('system', `File created: ${result.path}`)
      } else {
        showToast(result?.error || 'File save failed', 'error')
      }
    })
    .catch((error) => {
      hideLoader()
      showToast(error.message || 'File save failed', 'error')
    })

  return true
}

async function sendChat() {
  const message = els.chatInput.value.trim()
  if (!message && state.draftAttachments.length === 0) return

  const project = getContextProject()
  const attachments = state.draftAttachments.map((attachment) => ({
    filename: attachment.filename,
    mime_type: attachment.mime_type,
    data_url: attachment.data_url,
  }))

  if (project && state.draftAttachments.length) {
    await Promise.all(state.draftAttachments.map((attachment) => persistImageAttachment(project.id, attachment)))
  }

  renderMessage('user', message || 'Attachment', { attachments: state.draftAttachments })
  resetComposer()

  showLoader('Thinking...')
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
    }

    await loadConversations()
    renderContext()

    const saved = showGeneratedFile(response.reply || '', project?.watched_folder || null)
    if (!saved) {
      renderMessage('assistant', response.reply || '')
    }
  } catch (error) {
    showToast(error.message || 'Chat failed', 'error')
  } finally {
    hideLoader()
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
    showToast('Microphone access is not available in this app shell.', 'error')
    return
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    const audioContext = new (window.AudioContext || window.webkitAudioContext)()
    const analyser = audioContext.createAnalyser()
    analyser.fftSize = 1024
    const source = audioContext.createMediaStreamSource(stream)
    source.connect(analyser)

    const chunks = []
    const mediaRecorder = new MediaRecorder(stream)
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition
    const recognition = SpeechRecognition ? new SpeechRecognition() : null
    const transcriptState = { text: '', finalised: false }

    state.recording = {
      stream,
      audioContext,
      analyser,
      mediaRecorder,
      recognition,
      chunks,
      transcriptState,
      rafId: null,
    }
    state.isRecording = true
    els.micBtn.textContent = '⏹'
    els.voiceStatus.textContent = 'Recording...'
    els.voiceCanvas.classList.add('active')

    mediaRecorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) chunks.push(event.data)
    }

    mediaRecorder.onstop = async () => {
      const transcript = transcriptState.text.trim()
      state.recording = null
      stopRecordingUI()

      if (transcript) {
        els.chatInput.value = transcript
        resizeComposer()
        els.chatInput.focus()
        showToast('Voice text inserted into the composer')
      } else {
        showToast('No transcript was produced.', 'error')
      }
    }

    if (recognition) {
      recognition.lang = navigator.language || 'fr-FR'
      recognition.continuous = false
      recognition.interimResults = true
      recognition.onresult = (event) => {
        const parts = []
        for (let index = event.resultIndex; index < event.results.length; index += 1) {
          parts.push(event.results[index][0].transcript)
        }
        transcriptState.text = parts.join(' ').trim()
      }
      recognition.onerror = (event) => {
        showToast(`Speech recognition error: ${event.error}`, 'error')
      }
      recognition.onend = () => {
        transcriptState.finalised = true
      }
      try {
        recognition.start()
      } catch (error) {
        console.warn(error)
      }
    } else {
      showToast('Speech recognition is unavailable. The recorder will still capture audio.', 'error')
    }

    mediaRecorder.start()
    drawVoiceFrame()
  } catch (error) {
    showToast(error.message || 'Microphone permission denied', 'error')
    stopRecordingUI()
  }
}

function bindComposerEvents() {
  els.chatInput.addEventListener('input', resizeComposer)
  els.chatInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      sendChat()
    }
  })

  els.attachImageBtn.addEventListener('click', () => {
    els.imageInput.click()
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
  els.adminCreateUser.addEventListener('click', openCreateUserModal)
  els.logoutBtn.addEventListener('click', logout)
}

function bindAuthEvents() {
  els.loginButton.addEventListener('click', login)
  [els.email, els.password].forEach((input) => {
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault()
        login()
      }
    })
  })
}

async function bootstrap() {
  bindAuthEvents()
  bindSidebarEvents()
  bindComposerEvents()
  renderProjects()
  renderConversations()
  renderUsers()
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

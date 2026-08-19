import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import { open } from '@tauri-apps/plugin-dialog';

const projectSelect = document.getElementById('project-select');
const projectList = document.getElementById('project-list');
const projectSummary = document.getElementById('project-summary');
const chatForm = document.getElementById('chat-form');
const chatQuestion = document.getElementById('chat-question');
const chatButton = document.getElementById('chat-button');
const chatThread = document.getElementById('chat-thread');
const chatTitle = document.getElementById('chat-title');
const chatContext = document.getElementById('chat-context');
const sidebarModePill = document.getElementById('sidebar-mode-pill');
const statusPill = document.getElementById('status-pill');
const progressLabel = document.getElementById('progress-label');
const progressPercent = document.getElementById('progress-percent');
const progressBar = document.getElementById('progress-bar');

const projectSelectionKey = 'hippo-ai.desktop.project.selected';
const projectFormKey = 'hippo-ai.desktop.project.form';

let selectedProjectId = localStorage.getItem(projectSelectionKey) || '';
let projectRecords = [];
let currentProjectInventory = null;
let chatThreads = {};
let activeChatRequestId = null;
let activeChatUnlisten = null;

loadProjects();
renderActiveChatContext();
renderChatThread();

projectSelect.addEventListener('change', async () => {
  selectedProjectId = projectSelect.value || '';
  if (selectedProjectId) {
    localStorage.setItem(projectSelectionKey, selectedProjectId);
  } else {
    localStorage.removeItem(projectSelectionKey);
  }
  renderActiveChatContext();
  await loadSelectedProject();
  await loadChatThreadForSelection();
  renderChatThread();
});

projectList.addEventListener('click', async (event) => {
  const button = event.target.closest('[data-project-id]');
  if (!button) {
    return;
  }
  selectedProjectId = button.getAttribute('data-project-id') || '';
  projectSelect.value = selectedProjectId;
  if (selectedProjectId) {
    localStorage.setItem(projectSelectionKey, selectedProjectId);
  } else {
    localStorage.removeItem(projectSelectionKey);
  }
  renderActiveChatContext();
  await loadSelectedProject();
  await loadChatThreadForSelection();
  renderChatThread();
});

chatForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  await runChat();
});

function getChatThreadKey() {
  return selectedProjectId ? `project:${selectedProjectId}` : 'general';
}

function getChatThreadTitle() {
  if (!selectedProjectId) {
    return 'Allgemeiner Chat';
  }
  const project = projectRecords.find((record) => record.id === selectedProjectId);
  return project ? project.name : 'Projekt-Chat';
}

function getSelectedProject() {
  return projectRecords.find((record) => record.id === selectedProjectId) || null;
}

function renderActiveChatContext() {
  const project = projectRecords.find((record) => record.id === selectedProjectId) || null;
  if (!project) {
    sidebarModePill.textContent = 'Allgemeiner Chat';
    chatTitle.textContent = 'Allgemeiner Chat';
    chatContext.textContent = 'Der Chat läuft ohne Projektbezug. Wähle links ein Projekt aus, um projektbezogen zu arbeiten.';
    return;
  }

  sidebarModePill.textContent = project.name;
  chatTitle.textContent = project.name;
  const fileCount = project.metadata?.file_count ?? 0;
  const sourcePath = project.metadata?.source_path || project.root_path || '';
  chatContext.textContent = `${project.slug} · ${fileCount} Dateien · ${sourcePath}`;
}

function renderChatThread() {
  const key = getChatThreadKey();
  const messages = chatThreads[key] || [];
  if (!messages.length) {
    chatThread.innerHTML = `
      <div class="chat-empty chat-empty-minimal">
        Noch keine Nachricht. Stelle eine Frage, um den Chat zu beginnen.
      </div>
    `;
    return;
  }

  chatThread.innerHTML = messages
    .map((message) => renderChatMessage(message))
    .join('');
  scrollChatToBottom();
}

function renderChatMessage(message) {
  const roleClass = message.role === 'user' ? 'is-user' : 'is-assistant';
  const label = message.role === 'user' ? 'Du' : 'hippo-ai';
  const meta = message.created_at ? formatDateTime(message.created_at) : '';
  const content = escapeHtml(message.content || '').replaceAll('\n', '<br />');
  const sources = Array.isArray(message.sources) ? message.sources : [];
  const sourcesHtml = sources.length
    ? `
      <div class="chat-sources">
        ${sources
          .map((source) => `
            <div class="chat-source">
              <div class="chat-source-title">[${escapeHtml(source.id || 'S?')}] ${escapeHtml(source.title || source.file_name || 'Quelle')}</div>
              <div class="chat-source-meta">${escapeHtml(formatSourceMeta(source) || 'Ohne Metadaten')}</div>
              <div class="chat-source-path">${escapeHtml(source.relative_path || source.source_path || '')}</div>
              <div class="chat-source-snippet">${escapeHtml(source.snippet || '')}</div>
            </div>
          `)
          .join('')}
      </div>
    `
    : '';

  return `
    <article class="chat-message ${roleClass}">
      <div class="chat-meta">${escapeHtml(label)}${meta ? ` · ${escapeHtml(meta)}` : ''}</div>
      <div class="chat-bubble">${content || '&nbsp;'}</div>
      ${sourcesHtml}
    </article>
  `;
}

function formatSourceMeta(source) {
  return [
    source.species ? `Art: ${source.species}` : null,
    source.zone ? `Zone: ${source.zone}` : null,
    source.observed_at ? `Datum: ${source.observed_at}` : null,
    source.category ? `Kategorie: ${source.category}` : null,
  ]
    .filter(Boolean)
    .join(' · ');
}

async function runChat() {
  const question = chatQuestion.value.trim();
  if (!question) {
    return;
  }

  const key = getChatThreadKey();
  const messages = chatThreads[key] || [];
  const userMessage = {
    role: 'user',
    content: question,
    created_at: new Date().toISOString(),
  };
  const assistantMessage = {
    role: 'assistant',
    content: '',
    created_at: new Date().toISOString(),
    streaming: true,
    sources: [],
  };
  messages.push(userMessage, assistantMessage);
  chatThreads[key] = messages;
  renderChatThread();

  chatButton.disabled = true;
  setStatus('Läuft', 'running');
  setProgress('Antwort wird gestreamt', 22, true);
  chatQuestion.value = '';

  const requestId = crypto?.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  activeChatRequestId = requestId;

  if (activeChatUnlisten) {
    try {
      await activeChatUnlisten();
    } catch {
      // ignore
    }
    activeChatUnlisten = null;
  }

  activeChatUnlisten = await listen('hippo-ai-chat-stream', (event) => {
    const payload = event.payload || {};
    if (payload.request_id !== activeChatRequestId) {
      return;
    }

    if (payload.type === 'meta') {
      if (Array.isArray(payload.sources)) {
        assistantMessage.sources = payload.sources;
        renderChatThread();
      }
      return;
    }

    if (payload.type === 'delta') {
      assistantMessage.content = `${assistantMessage.content || ''}${String(payload.delta || '')}`;
      renderChatThread();
      return;
    }

    if (payload.type === 'final' && payload.response) {
      assistantMessage.content = payload.response.answer || assistantMessage.content;
      assistantMessage.sources = payload.response.sources || assistantMessage.sources;
      assistantMessage.streaming = false;
      renderChatThread();
      return;
    }
  });

  const payload = {
    question,
    species: null,
    file_type: null,
    category: null,
    zone: null,
    date_from: null,
    date_to: null,
    limit: 6,
    python_executable: null,
    project_root: null,
    request_id: requestId,
  };

  try {
    const result = selectedProjectId
      ? await invoke('chat_project_stream', { project_id: selectedProjectId, ...payload })
      : await invoke('chat_general_stream', payload);

    if (result.exit_code !== 0) {
      assistantMessage.content = result.stderr || result.stdout || `Chat fehlgeschlagen (Exit-Code ${result.exit_code})`;
      assistantMessage.sources = [];
      assistantMessage.streaming = false;
      renderChatThread();
      setStatus('Fehler', 'error');
      return;
    }

    const parsed = parseChatResult(result.stdout || '');
    assistantMessage.content = parsed.answer || assistantMessage.content || 'Keine Antwort erhalten.';
    assistantMessage.sources = parsed.sources || assistantMessage.sources || [];
    assistantMessage.streaming = false;
    renderChatThread();
    setStatus('Fertig', 'ready');
    await loadChatThreadForSelection();
    renderChatThread();
  } catch (error) {
    assistantMessage.content = `Chat fehlgeschlagen: ${error}`;
    assistantMessage.streaming = false;
    renderChatThread();
    setStatus('Fehler', 'error');
  } finally {
    activeChatRequestId = null;
    if (activeChatUnlisten) {
      try {
        await activeChatUnlisten();
      } catch {
        // ignore
      }
      activeChatUnlisten = null;
    }
    chatButton.disabled = false;
    setProgress('Bereit', 0, false);
  }
}

function parseChatResult(stdout) {
  if (!stdout || typeof stdout !== 'string') {
    return { sources: [] };
  }
  try {
    return JSON.parse(stdout);
  } catch {
    return { sources: [], raw: stdout };
  }
}

async function loadProjects(preferredProjectId = null) {
  try {
    const projects = await invoke('list_projects');
    projectRecords = Array.isArray(projects) ? projects : [];
    renderProjectSelect(projectRecords, preferredProjectId);
    renderProjectList(projectRecords);
    await loadSelectedProject();
    await loadChatThreadForSelection();
    renderChatThread();
  } catch (error) {
    projectSummary.textContent = `Projektliste konnte nicht geladen werden: ${error}`;
    projectList.innerHTML = '';
  }
}

function renderProjectSelect(projects, preferredProjectId = null) {
  const knownIds = new Set(projects.map((project) => project.id));
  const selectedId = preferredProjectId || selectedProjectId || '';

  projectSelect.innerHTML = '';
  const generalOption = document.createElement('option');
  generalOption.value = '';
  generalOption.textContent = 'Allgemeiner Chat';
  projectSelect.appendChild(generalOption);

  projects.forEach((project) => {
    const option = document.createElement('option');
    option.value = project.id;
    const fileCount = project.metadata?.file_count ?? 0;
    option.textContent = `${project.name} (${fileCount})`;
    projectSelect.appendChild(option);
  });

  if (selectedId && knownIds.has(selectedId)) {
    projectSelect.value = selectedId;
    selectedProjectId = selectedId;
    localStorage.setItem(projectSelectionKey, selectedId);
  } else if (!selectedId) {
    projectSelect.value = '';
    selectedProjectId = '';
    localStorage.removeItem(projectSelectionKey);
  } else {
    projectSelect.value = '';
    selectedProjectId = '';
    localStorage.removeItem(projectSelectionKey);
  }
}

function renderProjectList(projects) {
  if (!projects.length) {
    projectList.innerHTML = '<div class="history-empty">Noch keine Projekte angelegt.</div>';
    return;
  }

  projectList.innerHTML = projects
    .map((project) => {
      const fileCount = project.metadata?.file_count ?? 0;
      const active = project.id === selectedProjectId ? ' is-active' : '';
      return `
        <button type="button" class="project-chip${active}" data-project-id="${escapeHtml(project.id)}">
          <div class="project-chip-title">${escapeHtml(project.name)}</div>
          <div class="project-chip-meta">${escapeHtml(project.slug)} · ${escapeHtml(String(fileCount))} Dateien</div>
        </button>
      `;
    })
    .join('');
}

async function loadSelectedProject() {
  if (!selectedProjectId) {
    currentProjectInventory = null;
    projectSummary.textContent = 'Kein Projekt ausgewählt. Du kannst direkt im allgemeinen Chat arbeiten.';
    renderProjectList(projectRecords);
    renderActiveChatContext();
    currentProjectInventory = null;
    return;
  }

  try {
    const inventory = await invoke('get_project_inventory', { project_id: selectedProjectId });
    currentProjectInventory = inventory;
    renderProjectSummary(inventory);
    renderProjectList(projectRecords);
    renderActiveChatContext();
  } catch (error) {
    projectSummary.textContent = `Projektinventar konnte nicht geladen werden: ${error}`;
  }
}

async function loadChatThreadForSelection() {
  const key = getChatThreadKey();
  try {
    const messages = await invoke('load_chat_thread', { project_id: selectedProjectId || null });
    chatThreads[key] = Array.isArray(messages) ? messages : [];
  } catch {
    chatThreads[key] = chatThreads[key] || [];
  }
}

function renderProjectSummary(inventory) {
  if (!inventory) {
    projectSummary.textContent = 'Kein Projekt ausgewählt.';
    return;
  }

  const lines = [
    `Projekt: ${inventory.name || 'Projekt'}`,
    `Pfad: ${inventory.root_path || ''}`,
    `Quelle: ${inventory.source_path || inventory.root_path || ''}`,
    `Dateien: ${inventory.summary?.total_files ?? inventory.files?.length ?? 0}`,
    `Geodaten: ${inventory.summary?.geodata_files ?? 0}`,
    `Dokumente: ${inventory.summary?.document_files ?? 0}`,
    `Bilder: ${inventory.summary?.image_files ?? 0}`,
    `QGIS: ${inventory.summary?.qgis_files ?? 0}`,
    `Sonstige: ${inventory.summary?.other_files ?? 0}`,
  ];
  projectSummary.innerHTML = lines.map((line) => `<div>${escapeHtml(line)}</div>`).join('');
}

function getPrimaryGeodataPath(inventory = currentProjectInventory) {
  const files = Array.isArray(inventory?.files) ? inventory.files : [];
  const geodata = files.find((file) => file.category === 'geodata' && file.absolute_path);
  return geodata?.absolute_path || '';
}

function formatDateTime(value) {
  try {
    return new Date(value).toLocaleString('de-DE');
  } catch {
    return value;
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function setStatus(label, state = 'ready') {
  statusPill.textContent = label;
  statusPill.classList.remove('is-running', 'is-error');
  if (state === 'running') {
    statusPill.classList.add('is-running');
  } else if (state === 'error') {
    statusPill.classList.add('is-error');
  }
}

function setProgress(label, percent, active) {
  progressLabel.textContent = label;
  progressPercent.textContent = `${Math.max(0, Math.min(100, Math.round(percent)))}%`;
  progressBar.classList.toggle('is-active', active);
  progressBar.style.transform = active ? 'translateX(-100%)' : 'translateX(0)';
}

function scrollChatToBottom() {
  requestAnimationFrame(() => {
    chatThread.scrollTop = chatThread.scrollHeight;
  });
}

function startProgressCycle(stages = [
  { label: 'Modell wird vorbereitet', percent: 18 },
  { label: 'Kontext wird aufgebaut', percent: 42 },
  { label: 'Antwort wird erstellt', percent: 68 },
  { label: 'Ausgabe wird finalisiert', percent: 86 },
]) {
  let index = 0;
  return window.setInterval(() => {
    const stage = stages[index % stages.length];
    setProgress(stage.label, stage.percent, true);
    index += 1;
  }, 1400);
}

function stopProgressCycle(timer) {
  window.clearInterval(timer);
}

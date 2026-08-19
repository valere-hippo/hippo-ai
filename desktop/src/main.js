import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import { open } from '@tauri-apps/plugin-dialog';

const projectSelect = document.getElementById('project-select');
const projectList = document.getElementById('project-list');
const projectSummary = document.getElementById('project-summary');
const projectForm = document.getElementById('project-form');
const createProjectButton = document.getElementById('create-project-button');
const attachProjectButton = document.getElementById('attach-project-button');
const refreshProjectsButton = document.getElementById('refresh-projects-button');
const refreshProjectInventoryButton = document.getElementById('refresh-project-inventory-button');
const pickProjectFolderButton = document.querySelector('[data-action="pick-project-folder"]');
const chatForm = document.getElementById('chat-form');
const chatQuestion = document.getElementById('chat-question');
const chatButton = document.getElementById('chat-button');
const clearChatButton = document.getElementById('clear-chat-button');
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
const chatThreadsKey = 'hippo-ai.desktop.chat.threads';

let selectedProjectId = localStorage.getItem(projectSelectionKey) || '';
let projectRecords = [];
let chatThreads = loadChatThreads();
let activeChatRequestId = null;
let activeChatUnlisten = null;

restoreProjectFormState();
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
  renderChatThread();
  await loadSelectedProject();
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
  renderChatThread();
  await loadSelectedProject();
});

projectForm.addEventListener('input', persistProjectFormState);
projectForm.addEventListener('change', persistProjectFormState);

createProjectButton.addEventListener('click', async () => {
  const payload = getProjectPayload();
  if (!payload.name) {
    projectSummary.textContent = 'Bitte zuerst einen Projektnamen eingeben.';
    return;
  }

  createProjectButton.disabled = true;
  attachProjectButton.disabled = true;
  try {
    const project = await invoke('create_project', {
      name: payload.name,
      description: payload.description,
      client: payload.client,
      tags: splitTags(payload.tags),
      source_path: payload.source_path || null,
    });
    await loadProjects(project.id);
    projectSelect.value = project.id;
    selectedProjectId = project.id;
    localStorage.setItem(projectSelectionKey, selectedProjectId);
    renderActiveChatContext();
    renderChatThread();
    await loadSelectedProject();
    projectSummary.textContent = `Projekt "${project.name}" wurde angelegt.`;
  } catch (error) {
    projectSummary.textContent = `Projekt konnte nicht erstellt werden: ${error}`;
  } finally {
    createProjectButton.disabled = false;
    attachProjectButton.disabled = false;
  }
});

attachProjectButton.addEventListener('click', async () => {
  if (!selectedProjectId) {
    projectSummary.textContent = 'Bitte zuerst ein Projekt auswählen.';
    return;
  }

  const sourcePath = document.getElementById('project-source-path').value.trim();
  if (!sourcePath) {
    projectSummary.textContent = 'Bitte zuerst einen Quellordner auswählen.';
    return;
  }

  attachProjectButton.disabled = true;
  createProjectButton.disabled = true;
  try {
    await invoke('attach_project_folder', {
      project_id: selectedProjectId,
      source_path: sourcePath,
    });
    await loadProjects(selectedProjectId);
    await loadSelectedProject();
    projectSummary.textContent = 'Ordner wurde dem Projekt angehängt.';
  } catch (error) {
    projectSummary.textContent = `Ordner konnte nicht angehängt werden: ${error}`;
  } finally {
    attachProjectButton.disabled = false;
    createProjectButton.disabled = false;
  }
});

refreshProjectsButton.addEventListener('click', async () => {
  await loadProjects(selectedProjectId || null);
  await loadSelectedProject();
});

refreshProjectInventoryButton.addEventListener('click', async () => {
  if (!selectedProjectId) {
    projectSummary.textContent = 'Bitte zuerst ein Projekt auswählen.';
    return;
  }

  refreshProjectInventoryButton.disabled = true;
  try {
    const inventory = await invoke('refresh_project_inventory', { project_id: selectedProjectId });
    renderProjectSummary(inventory);
    projectSummary.textContent = 'Projektinhalt aktualisiert.';
  } catch (error) {
    projectSummary.textContent = `Projektinventar konnte nicht aktualisiert werden: ${error}`;
  } finally {
    refreshProjectInventoryButton.disabled = false;
  }
});

pickProjectFolderButton?.addEventListener('click', async () => {
  const selected = await open({
    multiple: false,
    directory: true,
    title: 'Projektordner oder Netzlaufwerk auswählen',
  });

  if (typeof selected === 'string' && selected.trim()) {
    document.getElementById('project-source-path').value = selected;
    persistProjectFormState();
  }
});

chatForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  await runChat();
});

clearChatButton.addEventListener('click', () => {
  const key = getChatThreadKey();
  chatThreads[key] = [];
  saveChatThreads();
  renderChatThread();
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
      <div class="chat-empty">
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
  saveChatThreads();
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
        saveChatThreads();
        renderChatThread();
      }
      return;
    }

    if (payload.type === 'delta') {
      assistantMessage.content = `${assistantMessage.content || ''}${String(payload.delta || '')}`;
      saveChatThreads();
      renderChatThread();
      return;
    }

    if (payload.type === 'final' && payload.response) {
      assistantMessage.content = payload.response.answer || assistantMessage.content;
      assistantMessage.sources = payload.response.sources || assistantMessage.sources;
      assistantMessage.streaming = false;
      saveChatThreads();
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
      saveChatThreads();
      renderChatThread();
      setStatus('Fehler', 'error');
      return;
    }

    const parsed = parseChatResult(result.stdout || '');
    assistantMessage.content = parsed.answer || assistantMessage.content || 'Keine Antwort erhalten.';
    assistantMessage.sources = parsed.sources || assistantMessage.sources || [];
    assistantMessage.streaming = false;
    saveChatThreads();
    renderChatThread();
    setStatus('Fertig', 'ready');
  } catch (error) {
    assistantMessage.content = `Chat fehlgeschlagen: ${error}`;
    assistantMessage.streaming = false;
    saveChatThreads();
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

function loadChatThreads() {
  const stored = localStorage.getItem(chatThreadsKey);
  if (!stored) {
    return {};
  }
  try {
    const parsed = JSON.parse(stored);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    localStorage.removeItem(chatThreadsKey);
    return {};
  }
}

function saveChatThreads() {
  localStorage.setItem(chatThreadsKey, JSON.stringify(chatThreads));
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
    projectSummary.textContent = 'Kein Projekt ausgewählt. Du kannst direkt im allgemeinen Chat arbeiten.';
    renderProjectList(projectRecords);
    renderActiveChatContext();
    return;
  }

  try {
    const inventory = await invoke('get_project_inventory', { project_id: selectedProjectId });
    renderProjectSummary(inventory);
    renderProjectList(projectRecords);
    renderActiveChatContext();
  } catch (error) {
    projectSummary.textContent = `Projektinventar konnte nicht geladen werden: ${error}`;
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

function getProjectPayload() {
  return {
    name: document.getElementById('project-name').value.trim(),
    description: document.getElementById('project-description').value.trim(),
    client: document.getElementById('project-client').value.trim(),
    tags: document.getElementById('project-tags').value.trim(),
    source_path: document.getElementById('project-source-path').value.trim(),
  };
}

function splitTags(value) {
  return value
    .split(/[;,]/)
    .map((tag) => tag.trim())
    .filter(Boolean);
}

function restoreProjectFormState() {
  const stored = localStorage.getItem(projectFormKey);
  if (!stored) {
    return;
  }
  try {
    const state = JSON.parse(stored);
    document.getElementById('project-name').value = typeof state.name === 'string' ? state.name : '';
    document.getElementById('project-description').value = typeof state.description === 'string' ? state.description : '';
    document.getElementById('project-client').value = typeof state.client === 'string' ? state.client : '';
    document.getElementById('project-tags').value = typeof state.tags === 'string' ? state.tags : '';
    document.getElementById('project-source-path').value = typeof state.source_path === 'string' ? state.source_path : '';
  } catch {
    localStorage.removeItem(projectFormKey);
  }
}

function persistProjectFormState() {
  localStorage.setItem(
    projectFormKey,
    JSON.stringify({
      name: document.getElementById('project-name').value,
      description: document.getElementById('project-description').value,
      client: document.getElementById('project-client').value,
      tags: document.getElementById('project-tags').value,
      source_path: document.getElementById('project-source-path').value,
    }),
  );
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

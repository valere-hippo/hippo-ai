import { invoke } from '@tauri-apps/api/core';
import { open, save } from '@tauri-apps/plugin-dialog';

const form = document.getElementById('analysis-form');
const projectForm = document.getElementById('project-form');
const runButton = document.getElementById('run-button');
const exportTxtButton = document.getElementById('export-txt-button');
const exportDocxButton = document.getElementById('export-docx-button');
const exportPdfButton = document.getElementById('export-pdf-button');
const resetButton = document.getElementById('reset-button');
const output = document.getElementById('result-output');
const statusPill = document.getElementById('status-pill');
const progressLabel = document.getElementById('progress-label');
const progressPercent = document.getElementById('progress-percent');
const progressBar = document.getElementById('progress-bar');
const historyList = document.getElementById('history-list');
const clearHistoryButton = document.getElementById('clear-history-button');
const loadHistoryButton = document.getElementById('load-history-button');
const createProjectButton = document.getElementById('create-project-button');
const attachProjectButton = document.getElementById('attach-project-button');
const refreshProjectsButton = document.getElementById('refresh-projects-button');
const refreshProjectInventoryButton = document.getElementById('refresh-project-inventory-button');
const detailEmpty = document.getElementById('detail-empty');
const detailView = document.getElementById('detail-view');
const detailTimestamp = document.getElementById('detail-timestamp');
const detailStatus = document.getElementById('detail-status');
const detailInput = document.getElementById('detail-input');
const detailOutput = document.getElementById('detail-output');
const detailCommand = document.getElementById('detail-command');
const detailStdout = document.getElementById('detail-stdout');
const detailStderr = document.getElementById('detail-stderr');
const projectSelect = document.getElementById('project-select');
const projectSummary = document.getElementById('project-summary');
const projectFileList = document.getElementById('project-file-list');
const pickInputButton = document.querySelector('[data-action="pick-input"]');
const pickOutputButton = document.querySelector('[data-action="pick-output"]');
const pickProjectFolderButton = document.querySelector('[data-action="pick-project-folder"]');
const storageKey = 'hippo-ai.desktop.form';
const historyKey = 'hippo-ai.desktop.history';
const projectFormKey = 'hippo-ai.desktop.project.form';
const projectSelectionKey = 'hippo-ai.desktop.project.selected';
const envReadyKey = 'hippo-ai.desktop.python-ready';
const advancedFields = [
  'python_executable',
  'project_root',
  'species_column',
  'date_column',
  'analysis_config_file',
  'rules_file',
  'docx_template_dir',
];
const visibleFields = ['input', 'output'];
const allFields = [...visibleFields, ...advancedFields];
let selectedHistoryIndex = null;
let selectedProjectId = localStorage.getItem(projectSelectionKey) || '';

restoreFormState();
restoreProjectFormState();
renderHistory();
renderDetails(null);
loadProjects();

allFields.forEach((name) => {
  const element = document.getElementById(name);
  if (element) {
    element.addEventListener('change', persistFormState);
  }
});

['project-name', 'project-description', 'project-client', 'project-tags', 'project-source-path'].forEach((name) => {
  const element = document.getElementById(name);
  if (element) {
    element.addEventListener('change', persistProjectFormState);
    element.addEventListener('input', persistProjectFormState);
  }
});

resetButton.addEventListener('click', () => {
  form.reset();
  document.getElementById('python_executable').value = '';
  document.getElementById('project_root').value = '';
  document.getElementById('species_column').value = '';
  document.getElementById('date_column').value = '';
  document.getElementById('analysis_config_file').value = '';
  document.getElementById('rules_file').value = '';
  document.getElementById('docx_template_dir').value = '';
  localStorage.removeItem(storageKey);
  output.textContent = 'Noch keine Analyse gestartet.';
  setStatus('Bereit');
  setProgress('Bereit zum Starten', 0, false);
});

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
    setStatus('Projekt erstellt');
    projectSummary.textContent = `Projekt "${project.name}" wurde erstellt.`;
  } catch (error) {
    projectSummary.textContent = `Projekt konnte nicht erstellt werden: ${error}`;
  } finally {
    createProjectButton.disabled = false;
    attachProjectButton.disabled = false;
  }
});

attachProjectButton.addEventListener('click', async () => {
  const payload = getProjectPayload();
  const projectId = selectedProjectId;
  if (!projectId) {
    projectSummary.textContent = 'Bitte zuerst ein Projekt auswählen.';
    return;
  }
  if (!payload.source_path) {
    projectSummary.textContent = 'Bitte zuerst einen Quellordner auswählen.';
    return;
  }

  attachProjectButton.disabled = true;
  createProjectButton.disabled = true;
  try {
    await invoke('attach_project_folder', {
      project_id: projectId,
      source_path: payload.source_path,
    });
    await loadProjects(projectId);
    setStatus('Ordner angehängt');
  } catch (error) {
    projectSummary.textContent = `Ordner konnte nicht angehängt werden: ${error}`;
  } finally {
    attachProjectButton.disabled = false;
    createProjectButton.disabled = false;
  }
});

refreshProjectsButton.addEventListener('click', async () => {
  await loadProjects(selectedProjectId || null);
});

refreshProjectInventoryButton.addEventListener('click', async () => {
  if (!selectedProjectId) {
    projectSummary.textContent = 'Bitte zuerst ein Projekt auswählen.';
    return;
  }

  refreshProjectInventoryButton.disabled = true;
  try {
    const inventory = await invoke('refresh_project_inventory', { project_id: selectedProjectId });
    renderProjectInventory(inventory);
    setStatus('Projekt gescannt');
  } catch (error) {
    projectSummary.textContent = `Projektinventar konnte nicht aktualisiert werden: ${error}`;
  } finally {
    refreshProjectInventoryButton.disabled = false;
  }
});

exportTxtButton.addEventListener('click', () => runDirectExport('txt', 'Text'));
exportDocxButton.addEventListener('click', () => runDirectExport('docx', 'Word'));
exportPdfButton.addEventListener('click', () => runDirectExport('pdf', 'PDF'));

clearHistoryButton.addEventListener('click', () => {
  localStorage.removeItem(historyKey);
  selectedHistoryIndex = null;
  renderHistory();
  renderDetails(null);
});

loadHistoryButton.addEventListener('click', () => {
  if (selectedHistoryIndex === null) {
    return;
  }
  const history = loadHistory();
  const entry = history[selectedHistoryIndex];
  if (!entry) {
    return;
  }
  loadHistoryEntry(entry);
});

pickInputButton.addEventListener('click', async () => {
  const selected = await open({
    multiple: false,
    directory: false,
    title: 'GeoPackage, Shape oder GeoJSON auswählen',
    filters: [
      { name: 'GeoPackage', extensions: ['gpkg'] },
      { name: 'Shape', extensions: ['shp'] },
      { name: 'GeoJSON', extensions: ['geojson', 'json'] },
    ],
  });

  if (typeof selected === 'string' && selected.trim()) {
    setInputPath(selected);
  }
});

pickOutputButton.addEventListener('click', async () => {
  const selected = await save({
    title: 'Ausgabedatei speichern',
    filters: [
      { name: 'Word', extensions: ['docx'] },
      { name: 'PDF', extensions: ['pdf'] },
      { name: 'Text', extensions: ['txt'] },
    ],
  });

  if (typeof selected === 'string' && selected.trim()) {
    document.getElementById('output').value = selected;
    persistFormState();
  }
});

pickProjectFolderButton.addEventListener('click', async () => {
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

projectSelect.addEventListener('change', async () => {
  selectedProjectId = projectSelect.value || '';
  localStorage.setItem(projectSelectionKey, selectedProjectId);
  await loadSelectedProject();
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();

  const payload = getCurrentPayload();

  if (!payload.input) {
    setStatus('Fehler', 'error');
    output.textContent = 'Bitte eine Eingabedatei angeben.';
    return;
  }

  if (!isSupportedInputFile(payload.input)) {
    setStatus('Fehler', 'error');
    output.textContent = [
      'Bitte eine GeoPackage-, Shape- oder GeoJSON-Datei auswählen.',
      'Dateien mit der Endung .cpg sind nur Begleitdateien und keine Analyse-Eingabe.',
    ].join('\n');
    return;
  }

  runButton.disabled = true;
  setStatus('Vorbereitung', 'running');
  setProgress('Python-Umgebung wird geprüft', 10, true);
  output.textContent = 'Python-Umgebung wird vorbereitet...';

  let progressTimer = null;
  try {
    persistFormState();
    await ensurePythonEnvironment(payload);
    setStatus('Läuft', 'running');
    setProgress('Analyse wird gestartet', 18, true);
    progressTimer = startProgressCycle();
    const result = await invoke('run_analysis', payload);
    stopProgressCycle(progressTimer);
    setProgress('Analyse abgeschlossen', 100, false);
    output.textContent = formatRunResult(result);
    setStatus(result.exit_code === 0 ? 'Fertig' : 'Fehler', result.exit_code === 0 ? 'ready' : 'error');
    addHistoryEntry({
      timestamp: new Date().toISOString(),
      input: payload.input,
      output: payload.output || '',
      exitCode: result.exit_code,
      command: result.command,
      python_executable: payload.python_executable,
      project_root: payload.project_root,
      species_column: payload.species_column,
      date_column: payload.date_column,
      analysis_config_file: payload.analysis_config_file,
      rules_file: payload.rules_file,
      docx_template_dir: payload.docx_template_dir,
      stdout: result.stdout || '',
      stderr: result.stderr || '',
    });
  } catch (error) {
    if (progressTimer !== null) {
      stopProgressCycle(progressTimer);
    }

    const errorText = String(error);
    if (errorText.includes("No module named 'pandas'")) {
      localStorage.removeItem(envReadyKey);
      try {
        output.textContent = 'Python-Umgebung wird nachinstalliert...';
        setStatus('Vorbereitung', 'running');
        setProgress('Python-Abhängigkeiten werden repariert', 35, true);
        await forcePreparePythonEnvironment(payload);
        const rerun = await invoke('run_analysis', payload);
        setProgress('Analyse abgeschlossen', 100, false);
        output.textContent = formatRunResult(rerun);
        setStatus(rerun.exit_code === 0 ? 'Fertig' : 'Fehler', rerun.exit_code === 0 ? 'ready' : 'error');
        addHistoryEntry({
          timestamp: new Date().toISOString(),
          input: payload.input,
          output: payload.output || '',
          exitCode: rerun.exit_code,
          command: rerun.command,
          python_executable: payload.python_executable,
          project_root: payload.project_root,
          species_column: payload.species_column,
          date_column: payload.date_column,
          analysis_config_file: payload.analysis_config_file,
          rules_file: payload.rules_file,
          docx_template_dir: payload.docx_template_dir,
          stdout: rerun.stdout || '',
          stderr: rerun.stderr || '',
        });
        return;
      } catch (retryError) {
        setProgress('Analyse fehlgeschlagen', 0, false);
        output.textContent = `Fehler beim Starten der Analyse:\n${retryError}`;
        setStatus('Fehler', 'error');
      }
    } else if (errorText.includes('Keine GeoPackage- oder Shape-Datei') || errorText.includes('GeoJSON')) {
      output.textContent = 'Bitte eine .gpkg-, .shp- oder .geojson-Datei auswählen. .cpg ist keine Analyse-Eingabe.';
      setStatus('Fehler', 'error');
    } else {
      setProgress('Analyse fehlgeschlagen', 0, false);
      output.textContent = `Fehler beim Starten der Analyse:\n${error}`;
      setStatus('Fehler', 'error');
    }
  } finally {
    runButton.disabled = false;
  }
});

function formatRunResult(result) {
  return [
    `Exit-Code: ${result.exit_code}`,
    '',
    'Kommando:',
    result.command,
    '',
    'stdout:',
    result.stdout || '(leer)',
    '',
    'stderr:',
    result.stderr || '(leer)',
  ].join('\n');
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

function getCurrentPayload() {
  return Object.fromEntries(
    allFields.map((name) => [name, document.getElementById(name).value.trim()]),
  );
}

function startProgressCycle(stages = [
  { label: 'Projekt wird vorbereitet', percent: 20 },
  { label: 'Analyse läuft', percent: 45 },
  { label: 'Bericht wird aufgebaut', percent: 70 },
  { label: 'Export wird abgeschlossen', percent: 88 },
]) {
  const cycle = stages;

  let index = 0;
  const timer = window.setInterval(() => {
    const stage = cycle[index % cycle.length];
    setProgress(stage.label, stage.percent, true);
    index += 1;
  }, 1400);

  return timer;
}

function stopProgressCycle(timer) {
  window.clearInterval(timer);
}

function persistFormState() {
  const state = Object.fromEntries(
    allFields.map((name) => [name, document.getElementById(name).value]),
  );
  localStorage.setItem(storageKey, JSON.stringify(state));
}

function restoreFormState() {
  const stored = localStorage.getItem(storageKey);
  if (!stored) {
    return;
  }

  try {
    const state = JSON.parse(stored);
    allFields.forEach((name) => {
      if (typeof state[name] === 'string') {
        document.getElementById(name).value = state[name];
      }
    });
  } catch {
    localStorage.removeItem(storageKey);
  }
}

function persistProjectFormState() {
  const state = {
    name: document.getElementById('project-name').value,
    description: document.getElementById('project-description').value,
    client: document.getElementById('project-client').value,
    tags: document.getElementById('project-tags').value,
    source_path: document.getElementById('project-source-path').value,
  };
  localStorage.setItem(projectFormKey, JSON.stringify(state));
}

function restoreProjectFormState() {
  const stored = localStorage.getItem(projectFormKey);
  if (!stored) {
    return;
  }

  try {
    const state = JSON.parse(stored);
    document.getElementById('project-name').value = typeof state.name === 'string' ? state.name : '';
    document.getElementById('project-description').value =
      typeof state.description === 'string' ? state.description : '';
    document.getElementById('project-client').value = typeof state.client === 'string' ? state.client : '';
    document.getElementById('project-tags').value = typeof state.tags === 'string' ? state.tags : '';
    document.getElementById('project-source-path').value =
      typeof state.source_path === 'string' ? state.source_path : '';
  } catch {
    localStorage.removeItem(projectFormKey);
  }
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

function loadHistory() {
  const stored = localStorage.getItem(historyKey);
  if (!stored) {
    return [];
  }

  try {
    const history = JSON.parse(stored);
    return Array.isArray(history) ? history : [];
  } catch {
    localStorage.removeItem(historyKey);
    return [];
  }
}

async function loadProjects(preferredProjectId = null) {
  try {
    const projects = await invoke('list_projects');
    renderProjectSelect(projects, preferredProjectId);
    if (selectedProjectId) {
      await loadSelectedProject();
    } else {
      renderProjectInventory(null);
    }
  } catch (error) {
    projectSummary.textContent = `Projektliste konnte nicht geladen werden: ${error}`;
    projectFileList.innerHTML = '';
  }
}

function renderProjectSelect(projects, preferredProjectId = null) {
  const selectedId = preferredProjectId || selectedProjectId || localStorage.getItem(projectSelectionKey) || '';
  projectSelect.innerHTML = '';

  const emptyOption = document.createElement('option');
  emptyOption.value = '';
  emptyOption.textContent = 'Kein Projekt ausgewählt';
  projectSelect.appendChild(emptyOption);

  projects.forEach((project) => {
    const option = document.createElement('option');
    option.value = project.id;
    const fileCount = project.metadata?.file_count ?? 0;
    option.textContent = `${project.name} (${project.slug}) · ${fileCount} Dateien`;
    projectSelect.appendChild(option);
  });

  const availableIds = new Set(projects.map((project) => project.id));
  if (selectedId && availableIds.has(selectedId)) {
    projectSelect.value = selectedId;
    selectedProjectId = selectedId;
    localStorage.setItem(projectSelectionKey, selectedId);
  } else if (projects.length > 0) {
    projectSelect.value = projects[0].id;
    selectedProjectId = projects[0].id;
    localStorage.setItem(projectSelectionKey, selectedProjectId);
  } else {
    selectedProjectId = '';
    localStorage.removeItem(projectSelectionKey);
  }
}

async function loadSelectedProject() {
  if (!selectedProjectId) {
    renderProjectInventory(null);
    return;
  }

  try {
    const inventory = await invoke('get_project_inventory', { project_id: selectedProjectId });
    renderProjectInventory(inventory);
  } catch (error) {
    projectSummary.textContent = `Projektinventar konnte nicht geladen werden: ${error}`;
    projectFileList.innerHTML = '';
  }
}

function renderProjectInventory(inventory) {
  if (!inventory) {
    projectSummary.innerHTML = 'Kein Projekt ausgewählt.';
    projectFileList.innerHTML = '<div class="history-empty">Noch keine Dateien gescannt.</div>';
    return;
  }

  const summaryLines = [
    `<strong>${escapeHtml(inventory.name || 'Projekt')}</strong>`,
    `Pfad: ${escapeHtml(inventory.root_path || '')}`,
    `Quelle: ${escapeHtml(inventory.source_path || inventory.root_path || '')}`,
    `Dateien: ${escapeHtml(String(inventory.summary?.total_files ?? inventory.files?.length ?? 0))}`,
    `Geodaten: ${escapeHtml(String(inventory.summary?.geodata_files ?? 0))}`,
    `Dokumente: ${escapeHtml(String(inventory.summary?.document_files ?? 0))}`,
    `Bilder: ${escapeHtml(String(inventory.summary?.image_files ?? 0))}`,
    `QGIS: ${escapeHtml(String(inventory.summary?.qgis_files ?? 0))}`,
    `Sonstige: ${escapeHtml(String(inventory.summary?.other_files ?? 0))}`,
    `Gescannt: ${escapeHtml(inventory.scanned_at || '')}`,
  ];
  projectSummary.innerHTML = summaryLines.map((line) => `<div>${line}</div>`).join('');

  const files = Array.isArray(inventory.files) ? inventory.files : [];
  if (!files.length) {
    projectFileList.innerHTML = '<div class="history-empty">Im Projekt wurden noch keine Dateien gefunden.</div>';
    return;
  }

  projectFileList.innerHTML = files
    .slice(0, 50)
    .map((file) => {
      const modified = file.modified_at ? ` · ${escapeHtml(file.modified_at)}` : '';
      return `
        <div class="project-file">
          <div class="project-file-top">
            <div class="project-file-name">${escapeHtml(file.file_name || file.relative_path)}</div>
            <div class="project-file-tag">${escapeHtml(file.category || 'other')}</div>
          </div>
          <div class="project-file-path">${escapeHtml(file.relative_path || file.absolute_path || '')}</div>
          <div class="project-file-meta">
            ${escapeHtml(file.extension || 'ohne Endung')} · ${escapeHtml(String(file.size_bytes || 0))} Bytes${modified}
          </div>
        </div>
      `;
    })
    .join('');
}

function saveHistory(entries) {
  localStorage.setItem(historyKey, JSON.stringify(entries.slice(0, 10)));
}

function addHistoryEntry(entry) {
  const history = loadHistory();
  history.unshift(entry);
  saveHistory(history);
  renderHistory();
  renderDetails({ ...entry, index: 0 });
}

function renderHistory() {
  const history = loadHistory();
  if (!history.length) {
    historyList.innerHTML = '<div class="history-empty">Noch keine Läufe gespeichert.</div>';
    return;
  }

  historyList.innerHTML = history
    .map((entry, index) => {
      const when = new Date(entry.timestamp).toLocaleString('de-DE');
      const statusText = entry.exitCode === 0 ? 'Erfolgreich' : `Fehler (${entry.exitCode})`;
      const isActive = index === selectedHistoryIndex ? ' is-active' : '';
      return `
        <button type="button" class="history-item${isActive}" data-history-index="${index}">
          <div class="history-top">
            <div>
              <div class="history-title">${escapeHtml(entry.input || 'Unbekannte Eingabe')}</div>
              <div class="history-meta">${escapeHtml(when)} · ${escapeHtml(statusText)}</div>
            </div>
            <div class="history-meta">${escapeHtml(entry.output || 'Keine Ausgabe')}</div>
          </div>
          <div class="history-command">${escapeHtml(entry.command || '')}</div>
        </button>
      `;
    })
    .join('');

  historyList.querySelectorAll('[data-history-index]').forEach((item) => {
    item.addEventListener('click', () => {
      const index = Number(item.getAttribute('data-history-index'));
      selectedHistoryIndex = Number.isNaN(index) ? null : index;
      const entry = history[index];
      renderDetails(entry ? { ...entry, index } : null);
      renderHistory();
    });
  });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function renderDetails(entry) {
  if (!entry) {
    detailEmpty.classList.remove('is-hidden');
    detailView.classList.add('is-hidden');
    loadHistoryButton.disabled = true;
    return;
  }

  detailEmpty.classList.add('is-hidden');
  detailView.classList.remove('is-hidden');
  loadHistoryButton.disabled = false;
  detailTimestamp.textContent = new Date(entry.timestamp).toLocaleString('de-DE');
  detailStatus.textContent = entry.exitCode === 0 ? 'Erfolgreich' : `Fehler (${entry.exitCode})`;
  detailInput.textContent = entry.input || 'Unbekannt';
  detailOutput.textContent = entry.output || 'Keine Ausgabe';
  detailCommand.textContent = entry.command || '';
  detailStdout.textContent = entry.stdout ? `stdout:\n${entry.stdout}` : 'stdout: (leer)';
  detailStderr.textContent = entry.stderr ? `stderr:\n${entry.stderr}` : 'stderr: (leer)';
}

function loadHistoryEntry(entry) {
  allFields.forEach((name) => {
    if (typeof entry[name] === 'string') {
      document.getElementById(name).value = entry[name];
    }
  });
  persistFormState();
  setStatus('Bereit');
  setProgress('Lauf geladen', 100, false);
  output.textContent = `Geladener Lauf:\n${entry.command || ''}`;
}

async function runDirectExport(extension, label) {
  const selected = await save({
    title: `${label}-Ausgabe speichern`,
    filters: [{ name: label, extensions: [extension] }],
  });

  if (typeof selected !== 'string' || !selected.trim()) {
    return;
  }

  document.getElementById('output').value = selected;
  persistFormState();
  await form.requestSubmit();
}

async function ensurePythonEnvironment(payload) {
  if (localStorage.getItem(envReadyKey) === 'true') {
    return;
  }

  const result = await invoke('prepare_environment', payload);
  if (result.exit_code !== 0) {
    throw new Error(formatRunResult(result));
  }

  localStorage.setItem(envReadyKey, 'true');
}

async function forcePreparePythonEnvironment(payload) {
  localStorage.removeItem(envReadyKey);
  await ensurePythonEnvironment(payload);
}

function setInputPath(value) {
  document.getElementById('input').value = value;
  persistFormState();
}

function isSupportedInputFile(path) {
  return /\.(gpkg|shp|geojson|json)$/i.test(path);
}

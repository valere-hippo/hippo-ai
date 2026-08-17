import { invoke } from '@tauri-apps/api/core';
import { open, save } from '@tauri-apps/plugin-dialog';

const form = document.getElementById('analysis-form');
const prepareButton = document.getElementById('prepare-button');
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
const detailEmpty = document.getElementById('detail-empty');
const detailView = document.getElementById('detail-view');
const detailTimestamp = document.getElementById('detail-timestamp');
const detailStatus = document.getElementById('detail-status');
const detailInput = document.getElementById('detail-input');
const detailOutput = document.getElementById('detail-output');
const detailCommand = document.getElementById('detail-command');
const detailStdout = document.getElementById('detail-stdout');
const detailStderr = document.getElementById('detail-stderr');
const pickInputButton = document.querySelector('[data-action="pick-input"]');
const pickOutputButton = document.querySelector('[data-action="pick-output"]');
const storageKey = 'tier-ai.desktop.form';
const historyKey = 'tier-ai.desktop.history';
let selectedHistoryIndex = null;

const fieldNames = [
  'python_executable',
  'project_root',
  'input',
  'output',
  'species_column',
  'date_column',
  'analysis_config_file',
  'rules_file',
  'docx_template_dir',
];

restoreFormState();
renderHistory();
renderDetails(null);

fieldNames.forEach((name) => {
  document.getElementById(name).addEventListener('change', persistFormState);
});

resetButton.addEventListener('click', () => {
  form.reset();
  document.getElementById('python_executable').value = 'py';
  document.getElementById('project_root').value = '..';
  document.getElementById('species_column').value = 'species';
  document.getElementById('date_column').value = 'observed_at';
  localStorage.removeItem(storageKey);
  output.textContent = 'Noch keine Analyse gestartet.';
  setStatus('Bereit');
  setProgress('Bereit zum Starten', 0, false);
});

prepareButton.addEventListener('click', async () => {
  const payload = getCurrentPayload();
  prepareButton.disabled = true;
  runButton.disabled = true;
  setStatus('Vorbereitung', 'running');
  setProgress('Python-Umgebung wird vorbereitet', 10, true);
  output.textContent = 'Python-Umgebung wird vorbereitet...';

  let progressTimer = null;
  try {
    persistFormState();
    progressTimer = startProgressCycle([
      { label: 'Virtuelle Umgebung wird erstellt', percent: 25 },
      { label: 'pip wird aktualisiert', percent: 50 },
      { label: 'Tier AI wird installiert', percent: 78 },
    ]);
    const result = await invoke('prepare_environment', payload);
    stopProgressCycle(progressTimer);
    setProgress('Python-Umgebung vorbereitet', 100, false);
    output.textContent = [
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
    setStatus(result.exit_code === 0 ? 'Bereit' : 'Fehler', result.exit_code === 0 ? 'ready' : 'error');
  } catch (error) {
    if (progressTimer !== null) {
      stopProgressCycle(progressTimer);
    }
    setProgress('Vorbereitung fehlgeschlagen', 0, false);
    output.textContent = `Fehler bei der Vorbereitung der Python-Umgebung:\n${error}`;
    setStatus('Fehler', 'error');
  } finally {
    prepareButton.disabled = false;
    runButton.disabled = false;
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
    title: 'GeoPackage oder Shape auswählen',
    filters: [
      { name: 'GeoPackage', extensions: ['gpkg'] },
      { name: 'Shape', extensions: ['shp'] },
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

form.addEventListener('submit', async (event) => {
  event.preventDefault();

  const payload = Object.fromEntries(
    fieldNames.map((name) => [name, document.getElementById(name).value.trim()]),
  );

  if (!payload.input) {
    setStatus('Fehler', 'error');
    output.textContent = 'Bitte eine Eingabedatei angeben.';
    return;
  }

  if (!isSupportedInputFile(payload.input)) {
    setStatus('Fehler', 'error');
    output.textContent = [
      'Bitte eine GeoPackage- oder Shape-Datei auswählen.',
      'Dateien mit der Endung .cpg sind nur Begleitdateien und keine Analyse-Eingabe.',
    ].join('\n');
    return;
  }

  runButton.disabled = true;
  setStatus('Läuft', 'running');
  setProgress('Vorbereitung', 15, true);
  output.textContent = 'Analyse wird gestartet...';

  let progressTimer = null;
  try {
    persistFormState();
    progressTimer = startProgressCycle();
    const result = await invoke('run_analysis', payload);
    stopProgressCycle(progressTimer);
    setProgress('Analyse abgeschlossen', 100, false);
    const lines = [
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
    ];
    output.textContent = lines.join('\n');
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
    setProgress('Analyse fehlgeschlagen', 0, false);
    if (String(error).includes("No module named 'pandas'")) {
      output.textContent = [
        'Die Python-Umgebung hat noch nicht alle Analyse-Abhängigkeiten.',
        'Nutze bitte zuerst „Python vorbereiten“ und starte die Analyse danach erneut.',
        '',
        `Fehler:\n${error}`,
      ].join('\n');
    } else if (String(error).includes('Keine GeoPackage- oder Shape-Datei')) {
      output.textContent = 'Bitte eine .gpkg- oder .shp-Datei auswählen. .cpg ist keine Analyse-Eingabe.';
    } else {
      output.textContent = `Fehler beim Starten der Analyse:\n${error}`;
    }
    setStatus('Fehler', 'error');
  } finally {
    runButton.disabled = false;
  }
});

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
    fieldNames.map((name) => [name, document.getElementById(name).value.trim()]),
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
    fieldNames.map((name) => [name, document.getElementById(name).value]),
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
    fieldNames.forEach((name) => {
      if (typeof state[name] === 'string') {
        document.getElementById(name).value = state[name];
      }
    });
  } catch {
    localStorage.removeItem(storageKey);
  }
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
  fieldNames.forEach((name) => {
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

function setInputPath(value) {
  document.getElementById('input').value = value;
  persistFormState();
}

function isSupportedInputFile(path) {
  return /\.(gpkg|shp)$/i.test(path);
}

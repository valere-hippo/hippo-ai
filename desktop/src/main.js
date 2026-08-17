import { invoke } from '@tauri-apps/api/core';
import { open, save } from '@tauri-apps/plugin-dialog';

const form = document.getElementById('analysis-form');
const runButton = document.getElementById('run-button');
const resetButton = document.getElementById('reset-button');
const output = document.getElementById('result-output');
const statusPill = document.getElementById('status-pill');
const progressLabel = document.getElementById('progress-label');
const progressPercent = document.getElementById('progress-percent');
const progressBar = document.getElementById('progress-bar');
const historyList = document.getElementById('history-list');
const clearHistoryButton = document.getElementById('clear-history-button');
const pickInputButton = document.querySelector('[data-action="pick-input"]');
const pickOutputButton = document.querySelector('[data-action="pick-output"]');
const storageKey = 'tier-ai.desktop.form';
const historyKey = 'tier-ai.desktop.history';

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

clearHistoryButton.addEventListener('click', () => {
  localStorage.removeItem(historyKey);
  renderHistory();
});

pickInputButton.addEventListener('click', async () => {
  const selected = await open({
    multiple: false,
    directory: false,
    title: 'GeoPackage oder Shape auswählen',
    filters: [
      { name: 'GeoPackage', extensions: ['gpkg'] },
      { name: 'Shape', extensions: ['shp'] },
      { name: 'Alle Dateien', extensions: ['*'] },
    ],
  });

  if (typeof selected === 'string' && selected.trim()) {
    document.getElementById('input').value = selected;
    persistFormState();
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
    });
  } catch (error) {
    if (progressTimer !== null) {
      stopProgressCycle(progressTimer);
    }
    setProgress('Analyse fehlgeschlagen', 0, false);
    output.textContent = `Fehler beim Starten der Analyse:\n${error}`;
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

function startProgressCycle() {
  const stages = [
    { label: 'Projekt wird vorbereitet', percent: 20 },
    { label: 'Analyse läuft', percent: 45 },
    { label: 'Bericht wird aufgebaut', percent: 70 },
    { label: 'Export wird abgeschlossen', percent: 88 },
  ];

  let index = 0;
  const timer = window.setInterval(() => {
    const stage = stages[index % stages.length];
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
}

function renderHistory() {
  const history = loadHistory();
  if (!history.length) {
    historyList.innerHTML = '<div class="history-empty">Noch keine Läufe gespeichert.</div>';
    return;
  }

  historyList.innerHTML = history
    .map((entry) => {
      const when = new Date(entry.timestamp).toLocaleString('de-DE');
      const statusText = entry.exitCode === 0 ? 'Erfolgreich' : `Fehler (${entry.exitCode})`;
      return `
        <article class="history-item">
          <div class="history-top">
            <div>
              <div class="history-title">${escapeHtml(entry.input || 'Unbekannte Eingabe')}</div>
              <div class="history-meta">${escapeHtml(when)} · ${escapeHtml(statusText)}</div>
            </div>
            <div class="history-meta">${escapeHtml(entry.output || 'Keine Ausgabe')}</div>
          </div>
          <div class="history-command">${escapeHtml(entry.command || '')}</div>
        </article>
      `;
    })
    .join('');
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

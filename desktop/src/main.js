import { invoke } from '@tauri-apps/api/core';
import { open, save } from '@tauri-apps/plugin-dialog';

const form = document.getElementById('analysis-form');
const runButton = document.getElementById('run-button');
const resetButton = document.getElementById('reset-button');
const output = document.getElementById('result-output');
const statusPill = document.getElementById('status-pill');
const pickInputButton = document.querySelector('[data-action="pick-input"]');
const pickOutputButton = document.querySelector('[data-action="pick-output"]');

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

resetButton.addEventListener('click', () => {
  form.reset();
  document.getElementById('python_executable').value = 'py';
  document.getElementById('project_root').value = '..';
  document.getElementById('species_column').value = 'species';
  document.getElementById('date_column').value = 'observed_at';
  output.textContent = 'Noch keine Analyse gestartet.';
  setStatus('Bereit');
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
  output.textContent = 'Analyse wird gestartet...';

  try {
    const result = await invoke('run_analysis', payload);
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
  } catch (error) {
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

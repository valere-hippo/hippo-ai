mod projects;

use projects::{ProjectCreateInput, ProjectInventory, ProjectRecord, ProjectStore};
use serde_json::Value;
use serde::Serialize;
use std::env;
use std::io::{BufRead, BufReader, Read};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::thread;
use tauri::Emitter;

#[derive(Serialize)]
struct AnalysisRunResult {
  exit_code: i32,
  command: String,
  stdout: String,
  stderr: String,
}

#[tauri::command]
fn prepare_environment(
  python_executable: Option<String>,
  project_root: Option<String>,
) -> Result<AnalysisRunResult, String> {
  let python = normalize_python_command(python_executable);
  let project_root = resolve_python_project_root(project_root.as_deref());
  let venv_dir = project_root.join(".venv");
  let venv_python = venv_python_path(&venv_dir);

  let mut command_steps = Vec::new();

  if !venv_python.exists() {
    let mut create_venv = Command::new(&python.command);
    create_venv.current_dir(&project_root);
    create_venv.args(&python.args);
    create_venv.args(["-m", "venv"]).arg(&venv_dir);
    let output = run_command(create_venv)
      .map_err(|error| format!("Python-Umgebung konnte nicht erstellt werden: {error}"))?;
    command_steps.push((format_argv(&python.command, &python.args, ["-m", "venv", venv_dir.to_string_lossy().as_ref()]), output));
  }

  let mut upgrade_pip = Command::new(&venv_python);
  upgrade_pip.current_dir(&project_root);
  upgrade_pip.args(["-m", "pip", "install", "--upgrade", "pip"]);
  let pip_output = run_command(upgrade_pip)
    .map_err(|error| format!("pip konnte nicht aktualisiert werden: {error}"))?;
  command_steps.push((format!("{} -m pip install --upgrade pip", venv_python.display()), pip_output));

  let mut install_project = Command::new(&venv_python);
  install_project.current_dir(&project_root);
  install_project.args(["-m", "pip", "install", "-e", "."]);
  let install_output = run_command(install_project)
    .map_err(|error| format!("Projekt konnte nicht installiert werden: {error}"))?;
  command_steps.push((format!("{} -m pip install -e .", venv_python.display()), install_output));

  let mut stdout = String::new();
  let mut stderr = String::new();
  let mut exit_code = 0;
  for (command, output) in command_steps {
    stdout.push_str("Kommando: ");
    stdout.push_str(&command);
    stdout.push('\n');
    stdout.push_str(&String::from_utf8_lossy(&output.stdout));
    stdout.push('\n');
    stderr.push_str(&String::from_utf8_lossy(&output.stderr));
    stderr.push('\n');
    exit_code = exit_code.max(output.status.code().unwrap_or(-1));
  }

  Ok(AnalysisRunResult {
    exit_code,
    command: format!("{} -m venv .venv && {} -m pip install -e .", python.command, venv_python.display()),
    stdout,
    stderr,
  })
}

#[tauri::command]
fn run_analysis(
  input: String,
  output: Option<String>,
  python_executable: Option<String>,
  project_root: Option<String>,
  species_column: Option<String>,
  date_column: Option<String>,
  analysis_config_file: Option<String>,
  rules_file: Option<String>,
  docx_template_dir: Option<String>,
) -> Result<AnalysisRunResult, String> {
  let project_root = resolve_python_project_root(project_root.as_deref());
  let python = resolve_python_executable(python_executable.as_deref(), &project_root);

  let src_path = project_root.join("src");
  let mut command = Command::new(&python.command);
  command.current_dir(&project_root);
  command.args(&python.args);
  command.env("PYTHONPATH", &src_path);
  command.arg("-m").arg("tier_ai").arg(&input);

  if let Some(value) = output.filter(|value| !value.trim().is_empty()) {
    command.arg("-o").arg(value);
  }
  if let Some(value) = species_column.filter(|value| !value.trim().is_empty()) {
    command.arg("--species-column").arg(value);
  }
  if let Some(value) = date_column.filter(|value| !value.trim().is_empty()) {
    command.arg("--date-column").arg(value);
  }
  if let Some(value) = analysis_config_file.filter(|value| !value.trim().is_empty()) {
    command.arg("--analysis-config-file").arg(value);
  }
  if let Some(value) = rules_file.filter(|value| !value.trim().is_empty()) {
    command.arg("--rules-file").arg(value);
  }
  if let Some(value) = docx_template_dir.filter(|value| !value.trim().is_empty()) {
    command.arg("--docx-template-dir").arg(value);
  }

  let display_command = format!(
    "{} {}",
    python.command,
    command
      .get_args()
      .map(|arg| arg.to_string_lossy().into_owned())
      .collect::<Vec<String>>()
      .join(" ")
  );

  let output = command
    .output()
    .map_err(|error| format!("Analyse konnte nicht gestartet werden: {error}"))?;

  let exit_code = output.status.code().unwrap_or(-1);
  Ok(AnalysisRunResult {
    exit_code,
    command: display_command,
    stdout: String::from_utf8_lossy(&output.stdout).into_owned(),
    stderr: String::from_utf8_lossy(&output.stderr).into_owned(),
  })
}

#[tauri::command]
fn list_projects() -> Result<Vec<ProjectRecord>, String> {
  project_store().list_projects()
}

#[tauri::command]
fn create_project(payload: ProjectCreateInput) -> Result<ProjectRecord, String> {
  project_store().create_project(payload)
}

#[tauri::command]
fn attach_project_folder(project_id: String, source_path: String) -> Result<ProjectRecord, String> {
  project_store().attach_project_folder(&project_id, &source_path)
}

#[tauri::command]
fn get_project_inventory(project_id: String) -> Result<ProjectInventory, String> {
  project_store().get_project_inventory(&project_id)
}

#[tauri::command]
fn refresh_project_inventory(project_id: String) -> Result<ProjectInventory, String> {
  project_store().refresh_project_inventory(&project_id)
}

#[tauri::command]
fn index_project(
  project_id: String,
  python_executable: Option<String>,
  project_root: Option<String>,
) -> Result<AnalysisRunResult, String> {
  let project = project_store().get_project(&project_id)?;
  let source_path = project
    .metadata
    .source_path
    .clone()
    .unwrap_or_else(|| project.root_path.clone());
  run_tier_ai_retrieval_command(
    "index",
    &project,
    python_executable,
    project_root,
    &[
      ("--source-root", Some(source_path)),
      ("--index-root", None),
      ("--no-qdrant", None),
    ],
  )
}

#[tauri::command]
fn search_project(
  project_id: String,
  query: String,
  species: Option<String>,
  file_type: Option<String>,
  category: Option<String>,
  zone: Option<String>,
  date_from: Option<String>,
  date_to: Option<String>,
  limit: Option<u32>,
  python_executable: Option<String>,
  project_root: Option<String>,
) -> Result<AnalysisRunResult, String> {
  let project = project_store().get_project(&project_id)?;
  let source_path = project
    .metadata
    .source_path
    .clone()
    .unwrap_or_else(|| project.root_path.clone());
  let mut extras: Vec<(&str, Option<String>)> = vec![
    ("--source-root", Some(source_path)),
    ("--query", Some(query)),
    ("--species", species),
    ("--file-type", file_type),
    ("--category", category),
    ("--zone", zone),
    ("--date-from", date_from),
    ("--date-to", date_to),
  ];
  if let Some(limit) = limit {
    extras.push(("--limit", Some(limit.to_string())));
  }

  run_tier_ai_retrieval_command("search", &project, python_executable, project_root, &extras)
}

#[tauri::command]
fn chat_project(
  project_id: String,
  question: String,
  species: Option<String>,
  file_type: Option<String>,
  category: Option<String>,
  zone: Option<String>,
  date_from: Option<String>,
  date_to: Option<String>,
  limit: Option<u32>,
  python_executable: Option<String>,
  project_root: Option<String>,
) -> Result<AnalysisRunResult, String> {
  let project = project_store().get_project(&project_id)?;
  let mut extras: Vec<(&str, Option<String>)> = vec![
    ("--question", Some(question)),
    ("--species", species),
    ("--file-type", file_type),
    ("--category", category),
    ("--zone", zone),
    ("--date-from", date_from),
    ("--date-to", date_to),
  ];
  if let Some(limit) = limit {
    extras.push(("--limit", Some(limit.to_string())));
  }

  run_tier_ai_chat_command(&project, python_executable, project_root, &extras)
}

#[tauri::command]
fn chat_project_stream(
  app: tauri::AppHandle,
  project_id: String,
  question: String,
  species: Option<String>,
  file_type: Option<String>,
  category: Option<String>,
  zone: Option<String>,
  date_from: Option<String>,
  date_to: Option<String>,
  limit: Option<u32>,
  python_executable: Option<String>,
  project_root: Option<String>,
  request_id: Option<String>,
) -> Result<AnalysisRunResult, String> {
  let project = project_store().get_project(&project_id)?;
  let mut extras: Vec<(&str, Option<String>)> = vec![
    ("--question", Some(question)),
    ("--species", species),
    ("--file-type", file_type),
    ("--category", category),
    ("--zone", zone),
    ("--date-from", date_from),
    ("--date-to", date_to),
    ("--stream", Some("true".to_string())),
  ];
  if let Some(limit) = limit {
    extras.push(("--limit", Some(limit.to_string())));
  }

  run_tier_ai_chat_command_stream(&app, &project, python_executable, project_root, request_id, &extras)
}

#[tauri::command]
fn chat_general(
  question: String,
  python_executable: Option<String>,
  project_root: Option<String>,
) -> Result<AnalysisRunResult, String> {
  let extras: Vec<(&str, Option<String>)> = vec![
    ("--general", Some("true".to_string())),
    ("--question", Some(question)),
  ];

  run_tier_ai_general_chat_command(python_executable, project_root, &extras)
}

#[tauri::command]
fn chat_general_stream(
  app: tauri::AppHandle,
  question: String,
  python_executable: Option<String>,
  project_root: Option<String>,
  request_id: Option<String>,
) -> Result<AnalysisRunResult, String> {
  let extras: Vec<(&str, Option<String>)> = vec![
    ("--general", Some("true".to_string())),
    ("--question", Some(question)),
    ("--stream", Some("true".to_string())),
  ];

  run_tier_ai_general_chat_command_stream(&app, python_executable, project_root, request_id, &extras)
}

fn main() {
  tauri::Builder::default()
    .plugin(tauri_plugin_dialog::init())
    .invoke_handler(tauri::generate_handler![
      run_analysis,
      prepare_environment,
      list_projects,
      create_project,
      attach_project_folder,
      get_project_inventory,
      refresh_project_inventory,
      index_project,
      search_project,
      chat_project,
      chat_project_stream,
      chat_general,
      chat_general_stream
    ])
    .run(tauri::generate_context!())
    .expect("error while running hippo-ai desktop app");
}

#[derive(Clone)]
struct PythonCommand {
  command: String,
  args: Vec<String>,
}

fn normalize_python_command(python_executable: Option<String>) -> PythonCommand {
  let command = python_executable
    .as_deref()
    .filter(|value| !value.trim().is_empty())
    .unwrap_or("py")
    .to_string();
  let mut args = Vec::new();
  if command.eq_ignore_ascii_case("py") {
    args.push("-3".to_string());
  }
  PythonCommand { command, args }
}

fn resolve_python_executable(python_executable: Option<&str>, project_root: &PathBuf) -> PythonCommand {
  let venv_python = venv_python_path(&project_root.join(".venv"));
  if venv_python.exists() {
    return PythonCommand {
      command: venv_python.to_string_lossy().into_owned(),
      args: Vec::new(),
    };
  }
  normalize_python_command(python_executable.map(|value| value.to_string()))
}

fn venv_python_path(venv_dir: &PathBuf) -> PathBuf {
  if cfg!(target_os = "windows") {
    venv_dir.join("Scripts").join("python.exe")
  } else {
    venv_dir.join("bin").join("python")
  }
}

fn resolve_python_project_root(project_root: Option<&str>) -> PathBuf {
  let raw = project_root
    .filter(|value| !value.trim().is_empty())
    .map(PathBuf::from)
    .unwrap_or_else(|| PathBuf::from(".."));
  let mut candidate = if raw.is_absolute() {
    raw
  } else {
    env::current_dir()
      .map(|cwd| cwd.join(raw))
      .unwrap_or_else(|_| PathBuf::from(".."))
  };

  candidate = candidate
    .canonicalize()
    .unwrap_or(candidate);

  locate_python_project_root(candidate)
}

fn locate_python_project_root(mut start: PathBuf) -> PathBuf {
  loop {
    if start.join("pyproject.toml").exists() || start.join("setup.py").exists() {
      return start;
    }

    if !start.pop() {
      return start;
    }
  }
}

fn run_command(mut command: Command) -> Result<std::process::Output, std::io::Error> {
  command.output()
}

fn format_argv<I, S>(command: &str, args: &[String], extra: I) -> String
where
  I: IntoIterator<Item = S>,
  S: AsRef<str>,
{
  let mut parts = vec![command.to_string()];
  parts.extend(args.iter().cloned());
  parts.extend(extra.into_iter().map(|arg| arg.as_ref().to_string()));
  parts.join(" ")
}

fn project_store() -> ProjectStore {
  ProjectStore::new()
}

fn run_tier_ai_retrieval_command(
  subcommand: &str,
  project: &ProjectRecord,
  python_executable: Option<String>,
  project_root: Option<String>,
  extras: &[(&str, Option<String>)],
) -> Result<AnalysisRunResult, String> {
  let project_root = resolve_python_project_root(project_root.as_deref());
  let python = resolve_python_executable(python_executable.as_deref(), &project_root);
  let src_path = project_root.join("src");

  let mut command = Command::new(&python.command);
  command.current_dir(&project_root);
  command.args(&python.args);
  command.env("PYTHONPATH", &src_path);
  command.arg("-m").arg("tier_ai.retrieval_cli").arg(subcommand);
  command.arg("--project-id").arg(&project.id);
  command.arg("--project-slug").arg(&project.slug);

  for (flag, value) in extras {
    if let Some(value) = value.as_ref().filter(|value| !value.trim().is_empty()) {
      command.arg(flag).arg(value);
    }
  }

  let display_command = format!(
    "{} {}",
    python.command,
    command
      .get_args()
      .map(|arg| arg.to_string_lossy().into_owned())
      .collect::<Vec<String>>()
      .join(" ")
  );

  let output = command
    .output()
    .map_err(|error| format!("Retrieval konnte nicht gestartet werden: {error}"))?;

  let exit_code = output.status.code().unwrap_or(-1);
  Ok(AnalysisRunResult {
    exit_code,
    command: display_command,
    stdout: String::from_utf8_lossy(&output.stdout).into_owned(),
    stderr: String::from_utf8_lossy(&output.stderr).into_owned(),
  })
}

fn run_tier_ai_chat_command(
  project: &ProjectRecord,
  python_executable: Option<String>,
  project_root: Option<String>,
  extras: &[(&str, Option<String>)],
) -> Result<AnalysisRunResult, String> {
  let project_root = resolve_python_project_root(project_root.as_deref());
  let python = resolve_python_executable(python_executable.as_deref(), &project_root);
  let src_path = project_root.join("src");

  let mut command = Command::new(&python.command);
  command.current_dir(&project_root);
  command.args(&python.args);
  command.env("PYTHONPATH", &src_path);
  command.arg("-m").arg("tier_ai.chat_cli");
  command.arg("--project-id").arg(&project.id);
  command.arg("--project-slug").arg(&project.slug);

  for (flag, value) in extras {
    if let Some(value) = value.as_ref().filter(|value| !value.trim().is_empty()) {
      command.arg(flag).arg(value);
    }
  }

  let display_command = format!(
    "{} {}",
    python.command,
    command
      .get_args()
      .map(|arg| arg.to_string_lossy().into_owned())
      .collect::<Vec<String>>()
      .join(" ")
  );

  let output = command
    .output()
    .map_err(|error| format!("Chat konnte nicht gestartet werden: {error}"))?;

  let exit_code = output.status.code().unwrap_or(-1);
  Ok(AnalysisRunResult {
    exit_code,
    command: display_command,
    stdout: String::from_utf8_lossy(&output.stdout).into_owned(),
    stderr: String::from_utf8_lossy(&output.stderr).into_owned(),
  })
}

fn run_tier_ai_chat_command_stream(
  app: &tauri::AppHandle,
  project: &ProjectRecord,
  python_executable: Option<String>,
  project_root: Option<String>,
  request_id: Option<String>,
  extras: &[(&str, Option<String>)],
) -> Result<AnalysisRunResult, String> {
  let project_root = resolve_python_project_root(project_root.as_deref());
  let python = resolve_python_executable(python_executable.as_deref(), &project_root);
  let src_path = project_root.join("src");
  let request_id = request_id.unwrap_or_else(|| uuid::Uuid::new_v4().to_string());

  let mut command = Command::new(&python.command);
  command.current_dir(&project_root);
  command.args(&python.args);
  command.env("PYTHONPATH", &src_path);
  command.arg("-m").arg("tier_ai.chat_cli");
  command.arg("--project-id").arg(&project.id);
  command.arg("--project-slug").arg(&project.slug);

  for (flag, value) in extras {
    if let Some(value) = value.as_ref().filter(|value| !value.trim().is_empty()) {
      command.arg(flag).arg(value);
    }
  }

  let display_command = format!(
    "{} {}",
    python.command,
    command
      .get_args()
      .map(|arg| arg.to_string_lossy().into_owned())
      .collect::<Vec<String>>()
      .join(" ")
  );

  command.stdout(Stdio::piped());
  command.stderr(Stdio::piped());

  let mut child = command
    .spawn()
    .map_err(|error| format!("Chat konnte nicht gestartet werden: {error}"))?;
  let stdout = child
    .stdout
    .take()
    .ok_or_else(|| "Chat-stdout konnte nicht gelesen werden".to_string())?;
  let stderr = child
    .stderr
    .take()
    .ok_or_else(|| "Chat-stderr konnte nicht gelesen werden".to_string())?;

  let app_for_stdout = app.clone();
  let request_id_for_stdout = request_id.clone();
  let stdout_handle = thread::spawn(move || {
    let reader = BufReader::new(stdout);
    let mut collected_stdout = String::new();
    let mut final_json = String::new();
    for line in reader.lines() {
      match line {
        Ok(raw_line) => {
          if raw_line.trim().is_empty() {
            continue;
          }
          collected_stdout.push_str(&raw_line);
          collected_stdout.push('\n');
          if let Ok(mut payload) = serde_json::from_str::<Value>(&raw_line) {
            if let Some(object) = payload.as_object_mut() {
              object.insert("request_id".to_string(), Value::String(request_id_for_stdout.clone()));
            }
            let event_type = payload
              .get("type")
              .and_then(|value| value.as_str())
              .unwrap_or_default()
              .to_string();
            let _ = app_for_stdout.emit("hippo-ai-chat-stream", payload.clone());
            if event_type == "final" {
              if let Some(response) = payload.get("response") {
                if let Ok(serialized) = serde_json::to_string_pretty(response) {
                  final_json = serialized;
                }
              }
            }
          }
        }
        Err(_) => {}
      }
    }
    (collected_stdout, final_json)
  });

  let stderr_handle = thread::spawn(move || {
    let mut reader = BufReader::new(stderr);
    let mut collected = String::new();
    let _ = reader.read_to_string(&mut collected);
    collected
  });

  let status = child
    .wait()
    .map_err(|error| format!("Chat-Prozess konnte nicht beendet werden: {error}"))?;

  let (stdout_text, final_json) = stdout_handle
    .join()
    .map_err(|_| "Chat-stdout thread panicked".to_string())?;
  let stderr_text = stderr_handle
    .join()
    .map_err(|_| "Chat-stderr thread panicked".to_string())?;

  let final_stdout = if final_json.trim().is_empty() {
    stdout_text
  } else {
    final_json
  };

  Ok(AnalysisRunResult {
    exit_code: status.code().unwrap_or(-1),
    command: display_command,
    stdout: final_stdout,
    stderr: stderr_text,
  })
}

fn run_tier_ai_general_chat_command(
  python_executable: Option<String>,
  project_root: Option<String>,
  extras: &[(&str, Option<String>)],
) -> Result<AnalysisRunResult, String> {
  let project_root = resolve_python_project_root(project_root.as_deref());
  let python = resolve_python_executable(python_executable.as_deref(), &project_root);
  let src_path = project_root.join("src");

  let mut command = Command::new(&python.command);
  command.current_dir(&project_root);
  command.args(&python.args);
  command.env("PYTHONPATH", &src_path);
  command.arg("-m").arg("tier_ai.chat_cli");

  for (flag, value) in extras {
    if let Some(value) = value.as_ref().filter(|value| !value.trim().is_empty()) {
      command.arg(flag).arg(value);
    }
  }

  let display_command = format!(
    "{} {}",
    python.command,
    command
      .get_args()
      .map(|arg| arg.to_string_lossy().into_owned())
      .collect::<Vec<String>>()
      .join(" ")
  );

  let output = command
    .output()
    .map_err(|error| format!("Chat konnte nicht gestartet werden: {error}"))?;

  let exit_code = output.status.code().unwrap_or(-1);
  Ok(AnalysisRunResult {
    exit_code,
    command: display_command,
    stdout: String::from_utf8_lossy(&output.stdout).into_owned(),
    stderr: String::from_utf8_lossy(&output.stderr).into_owned(),
  })
}

fn run_tier_ai_general_chat_command_stream(
  app: &tauri::AppHandle,
  python_executable: Option<String>,
  project_root: Option<String>,
  request_id: Option<String>,
  extras: &[(&str, Option<String>)],
) -> Result<AnalysisRunResult, String> {
  let project_root = resolve_python_project_root(project_root.as_deref());
  let python = resolve_python_executable(python_executable.as_deref(), &project_root);
  let src_path = project_root.join("src");
  let request_id = request_id.unwrap_or_else(|| uuid::Uuid::new_v4().to_string());

  let mut command = Command::new(&python.command);
  command.current_dir(&project_root);
  command.args(&python.args);
  command.env("PYTHONPATH", &src_path);
  command.arg("-m").arg("tier_ai.chat_cli");

  for (flag, value) in extras {
    if let Some(value) = value.as_ref().filter(|value| !value.trim().is_empty()) {
      command.arg(flag).arg(value);
    }
  }

  let display_command = format!(
    "{} {}",
    python.command,
    command
      .get_args()
      .map(|arg| arg.to_string_lossy().into_owned())
      .collect::<Vec<String>>()
      .join(" ")
  );

  command.stdout(Stdio::piped());
  command.stderr(Stdio::piped());

  let mut child = command
    .spawn()
    .map_err(|error| format!("Chat konnte nicht gestartet werden: {error}"))?;
  let stdout = child
    .stdout
    .take()
    .ok_or_else(|| "Chat-stdout konnte nicht gelesen werden".to_string())?;
  let stderr = child
    .stderr
    .take()
    .ok_or_else(|| "Chat-stderr konnte nicht gelesen werden".to_string())?;

  let app_for_stdout = app.clone();
  let request_id_for_stdout = request_id.clone();
  let stdout_handle = thread::spawn(move || {
    let reader = BufReader::new(stdout);
    let mut collected_stdout = String::new();
    let mut final_json = String::new();
    for line in reader.lines() {
      match line {
        Ok(raw_line) => {
          if raw_line.trim().is_empty() {
            continue;
          }
          collected_stdout.push_str(&raw_line);
          collected_stdout.push('\n');
          if let Ok(mut payload) = serde_json::from_str::<Value>(&raw_line) {
            if let Some(object) = payload.as_object_mut() {
              object.insert("request_id".to_string(), Value::String(request_id_for_stdout.clone()));
            }
            let event_type = payload
              .get("type")
              .and_then(|value| value.as_str())
              .unwrap_or_default()
              .to_string();
            let _ = app_for_stdout.emit("hippo-ai-chat-stream", payload.clone());
            if event_type == "final" {
              if let Some(response) = payload.get("response") {
                if let Ok(serialized) = serde_json::to_string_pretty(response) {
                  final_json = serialized;
                }
              }
            }
          }
        }
        Err(_) => {}
      }
    }
    (collected_stdout, final_json)
  });

  let stderr_handle = thread::spawn(move || {
    let mut reader = BufReader::new(stderr);
    let mut collected = String::new();
    let _ = reader.read_to_string(&mut collected);
    collected
  });

  let status = child
    .wait()
    .map_err(|error| format!("Chat-Prozess konnte nicht beendet werden: {error}"))?;

  let (stdout_text, final_json) = stdout_handle
    .join()
    .map_err(|_| "Chat-stdout thread panicked".to_string())?;
  let stderr_text = stderr_handle
    .join()
    .map_err(|_| "Chat-stderr thread panicked".to_string())?;

  let final_stdout = if final_json.trim().is_empty() {
    stdout_text
  } else {
    final_json
  };

  Ok(AnalysisRunResult {
    exit_code: status.code().unwrap_or(-1),
    command: display_command,
    stdout: final_stdout,
    stderr: stderr_text,
  })
}

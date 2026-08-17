use serde::Serialize;
use std::path::PathBuf;
use std::process::Command;

#[derive(Serialize)]
struct AnalysisRunResult {
  exit_code: i32,
  command: String,
  stdout: String,
  stderr: String,
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
  let python = python_executable
    .as_deref()
    .filter(|value| !value.trim().is_empty())
    .unwrap_or("py");

  let project_root = project_root
    .as_deref()
    .filter(|value| !value.trim().is_empty())
    .map(PathBuf::from)
    .unwrap_or_else(|| PathBuf::from(".."));

  let src_path = project_root.join("src");
  let mut command = Command::new(python);
  command.current_dir(&project_root);
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
    "{} -m tier_ai {}",
    python,
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

fn main() {
  tauri::Builder::default()
    .plugin(tauri_plugin_dialog::init())
    .invoke_handler(tauri::generate_handler![run_analysis])
    .run(tauri::generate_context!())
    .expect("error while running tier-ai desktop app");
}

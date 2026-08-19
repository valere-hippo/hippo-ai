use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use serde_json::Value;

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ProjectMetadata {
  #[serde(default = "default_metadata_source")]
  pub source: String,
  #[serde(default)]
  pub source_path: Option<String>,
  #[serde(default)]
  pub inventory_path: Option<String>,
  #[serde(default)]
  pub attached: bool,
  #[serde(default)]
  pub file_count: usize,
  #[serde(default)]
  pub geodata_count: usize,
  #[serde(default)]
  pub document_count: usize,
  #[serde(default)]
  pub image_count: usize,
  #[serde(default)]
  pub qgis_count: usize,
  #[serde(default)]
  pub other_count: usize,
  #[serde(default)]
  pub scanned_at: Option<String>,
}

fn default_metadata_source() -> String {
  "manual".to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProjectRecord {
  pub id: String,
  pub slug: String,
  pub name: String,
  #[serde(default)]
  pub description: String,
  #[serde(default)]
  pub client: String,
  #[serde(default)]
  pub tags: Vec<String>,
  #[serde(default = "default_project_status")]
  pub status: String,
  pub root_path: String,
  pub created_at: String,
  pub updated_at: String,
  #[serde(default)]
  pub directories: BTreeMap<String, String>,
  #[serde(default)]
  pub metadata: ProjectMetadata,
}

fn default_project_status() -> String {
  "active".to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProjectCreateInput {
  pub name: String,
  #[serde(default)]
  pub description: String,
  #[serde(default)]
  pub client: String,
  #[serde(default)]
  pub tags: Vec<String>,
  #[serde(default)]
  pub source_path: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProjectFileEntry {
  pub relative_path: String,
  pub absolute_path: String,
  pub file_name: String,
  pub extension: String,
  pub category: String,
  pub size_bytes: u64,
  pub modified_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ProjectInventorySummary {
  pub total_files: usize,
  pub geodata_files: usize,
  pub document_files: usize,
  pub image_files: usize,
  pub qgis_files: usize,
  pub other_files: usize,
  #[serde(default)]
  pub by_extension: BTreeMap<String, usize>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProjectInventory {
  pub project_id: String,
  pub slug: String,
  pub name: String,
  pub root_path: String,
  pub source_path: Option<String>,
  pub scanned_at: String,
  pub summary: ProjectInventorySummary,
  pub files: Vec<ProjectFileEntry>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ChatMessageRecord {
  pub role: String,
  pub content: String,
  pub created_at: String,
  #[serde(default)]
  pub streaming: bool,
  #[serde(default)]
  pub backend: Option<String>,
  #[serde(default)]
  pub model_name: Option<String>,
  #[serde(default)]
  pub citations: Vec<String>,
  #[serde(default)]
  pub sources: Vec<Value>,
  #[serde(default)]
  pub project_id: Option<String>,
  #[serde(default)]
  pub project_slug: Option<String>,
}

#[derive(Clone)]
pub struct ProjectStore {
  workspace_root: PathBuf,
  projects_dir: PathBuf,
  state_dir: PathBuf,
  registry_path: PathBuf,
}

impl ProjectStore {
  pub fn new() -> Self {
    let workspace_root = resolve_workspace_root();
    let workspace_dir = workspace_root.join("workspace");
    let projects_dir = workspace_dir.join("projects");
    let state_dir = workspace_dir.join("state");
    let registry_path = state_dir.join("projects.json");

    fs::create_dir_all(&projects_dir).ok();
    fs::create_dir_all(&state_dir).ok();
    if !registry_path.exists() {
      fs::write(&registry_path, "[]").ok();
    }

    Self {
      workspace_root,
      projects_dir,
      state_dir,
      registry_path,
    }
  }

  pub fn list_projects(&self) -> Result<Vec<ProjectRecord>, String> {
    self.load_registry()
  }

  pub fn get_project(&self, project_id: &str) -> Result<ProjectRecord, String> {
    let registry = self.load_registry()?;
    registry
      .into_iter()
      .find(|project| project.id == project_id || project.slug == project_id)
      .ok_or_else(|| "Projekt nicht gefunden".to_string())
  }

  pub fn create_project(&self, payload: ProjectCreateInput) -> Result<ProjectRecord, String> {
    let name = payload.name.trim();
    if name.is_empty() {
      return Err("Projektname fehlt".to_string());
    }

    let created_at = now_iso();
    let slug = self.unique_slug(name)?;
    let project_id = uuid_hex();
    let root_path = self.projects_dir.join(&slug);
    let directories = self.create_project_directories(&root_path)?;
    let mut record = ProjectRecord {
      id: project_id,
      slug,
      name: name.to_string(),
      description: payload.description.trim().to_string(),
      client: payload.client.trim().to_string(),
      tags: normalize_tags(&payload.tags),
      status: "active".to_string(),
      root_path: root_path.to_string_lossy().into_owned(),
      created_at: created_at.clone(),
      updated_at: created_at,
      directories,
      metadata: ProjectMetadata {
        source: "manual".to_string(),
        ..ProjectMetadata::default()
      },
    };

    self.write_project_manifest(&record)?;

    if let Some(source_path) = payload.source_path {
      if !source_path.trim().is_empty() {
        let source_root = normalize_source_path(Path::new(source_path.trim()));
        let inventory = self.scan_and_store_inventory(&record, &source_root)?;
        record.metadata = metadata_from_inventory(
          "manual",
          Some(source_root.to_string_lossy().into_owned()),
          Some(&inventory),
        );
        record.updated_at = inventory.scanned_at.clone();
        self.write_project_manifest(&record)?;
      }
    }

    self.save_record(&record)?;
    Ok(record)
  }

  pub fn attach_project_folder(&self, project_id: &str, source_path: &str) -> Result<ProjectRecord, String> {
    if source_path.trim().is_empty() {
      return Err("Ordnerpfad fehlt".to_string());
    }

    let mut project = self.get_project(project_id)?;
    let source_root = normalize_source_path(Path::new(source_path.trim()));
    let inventory = self.scan_and_store_inventory(&project, &source_root)?;
    project.metadata = metadata_from_inventory(
      "attached",
      Some(source_root.to_string_lossy().into_owned()),
      Some(&inventory),
    );
    project.updated_at = inventory.scanned_at.clone();
    self.write_project_manifest(&project)?;
    self.save_record(&project)?;
    Ok(project)
  }

  pub fn get_project_inventory(&self, project_id: &str) -> Result<ProjectInventory, String> {
    let project = self.get_project(project_id)?;
    let inventory_path = self.project_root(&project).join("inventory.json");
    if inventory_path.exists() {
      let text = fs::read_to_string(&inventory_path).map_err(io_error)?;
      return serde_json::from_str(&text).map_err(|error| format!("Inventar konnte nicht gelesen werden: {error}"));
    }

    let source_root = self.project_source_root(&project);
    self.scan_and_store_inventory(&project, &source_root)
  }

  pub fn refresh_project_inventory(&self, project_id: &str) -> Result<ProjectInventory, String> {
    let project = self.get_project(project_id)?;
    let source_root = self.project_source_root(&project);
    let inventory = self.scan_and_store_inventory(&project, &source_root)?;
    let mut updated = project.clone();
    updated.updated_at = inventory.scanned_at.clone();
    updated.metadata = metadata_from_inventory(
      &updated.metadata.source,
      updated.metadata.source_path.clone(),
      Some(&inventory),
    );
    self.write_project_manifest(&updated)?;
    self.save_record(&updated)?;
    Ok(inventory)
  }

  fn load_registry(&self) -> Result<Vec<ProjectRecord>, String> {
    let text = fs::read_to_string(&self.registry_path).map_err(io_error)?;
    let records = if text.trim().is_empty() {
      Vec::new()
    } else {
      serde_json::from_str::<Vec<ProjectRecord>>(&text)
        .map_err(|error| format!("Projektregistry konnte nicht gelesen werden: {error}"))?
    };
    Ok(records)
  }

  fn save_registry(&self, records: &[ProjectRecord]) -> Result<(), String> {
    let serialized = serde_json::to_string_pretty(records)
      .map_err(|error| format!("Projektregistry konnte nicht geschrieben werden: {error}"))?;
    fs::write(&self.registry_path, serialized).map_err(io_error)
  }

  fn save_record(&self, record: &ProjectRecord) -> Result<(), String> {
    let mut registry = self.load_registry()?;
    registry.retain(|item| item.id != record.id && item.slug != record.slug);
    registry.push(record.clone());
    self.save_registry(&registry)
  }

  fn create_project_directories(&self, root_path: &Path) -> Result<BTreeMap<String, String>, String> {
    fs::create_dir_all(root_path).map_err(io_error)?;
    let mut directories = BTreeMap::new();
    for name in ["input", "analysis", "reports", "exports", "notes", "attachments"] {
      let path = root_path.join(name);
      fs::create_dir_all(&path).map_err(io_error)?;
      directories.insert(name.to_string(), path.to_string_lossy().into_owned());
    }
    let chat_path = root_path.join("chat");
    fs::create_dir_all(&chat_path).map_err(io_error)?;
    directories.insert("chat".to_string(), chat_path.to_string_lossy().into_owned());
    Ok(directories)
  }

  fn write_project_manifest(&self, record: &ProjectRecord) -> Result<(), String> {
    let manifest_path = self.project_root(record).join("manifest.json");
    let serialized = serde_json::to_string_pretty(record)
      .map_err(|error| format!("Projektmanifest konnte nicht geschrieben werden: {error}"))?;
    fs::write(manifest_path, serialized).map_err(io_error)
  }

  fn scan_and_store_inventory(&self, project: &ProjectRecord, source_root: &Path) -> Result<ProjectInventory, String> {
    if !source_root.exists() {
      return Err(format!("Quellordner nicht gefunden: {}", source_root.display()));
    }

    let mut files = Vec::new();
    self.collect_files(source_root, source_root, &mut files)?;
    files.sort_by(|left, right| left.relative_path.cmp(&right.relative_path));

    let mut summary = ProjectInventorySummary::default();
    summary.total_files = files.len();

    for file in &files {
      *summary.by_extension.entry(file.extension.clone()).or_insert(0) += 1;
      match file.category.as_str() {
        "geodata" => summary.geodata_files += 1,
        "document" => summary.document_files += 1,
        "image" => summary.image_files += 1,
        "qgis" => summary.qgis_files += 1,
        _ => summary.other_files += 1,
      }
    }

    let inventory = ProjectInventory {
      project_id: project.id.clone(),
      slug: project.slug.clone(),
      name: project.name.clone(),
      root_path: project.root_path.clone(),
      source_path: Some(source_root.to_string_lossy().into_owned()),
      scanned_at: now_iso(),
      summary,
      files,
    };

    let inventory_path = self.project_root(project).join("inventory.json");
    let serialized = serde_json::to_string_pretty(&inventory)
      .map_err(|error| format!("Inventar konnte nicht geschrieben werden: {error}"))?;
    fs::write(&inventory_path, serialized).map_err(io_error)?;
    Ok(inventory)
  }

  fn collect_files(&self, root: &Path, current: &Path, files: &mut Vec<ProjectFileEntry>) -> Result<(), String> {
    for entry in fs::read_dir(current).map_err(io_error)? {
      let entry = entry.map_err(io_error)?;
      let path = entry.path();
      let metadata = entry.metadata().map_err(io_error)?;

      if metadata.is_dir() {
        self.collect_files(root, &path, files)?;
        continue;
      }

      if !metadata.is_file() {
        continue;
      }

      let relative_path = path
        .strip_prefix(root)
        .unwrap_or(path.as_path())
        .to_string_lossy()
        .replace('\\', "/");
      let file_name = path
        .file_name()
        .map(|value| value.to_string_lossy().into_owned())
        .unwrap_or_else(|| relative_path.clone());
      if file_name == "manifest.json" || file_name == "inventory.json" {
        continue;
      }
      let extension = path
        .extension()
        .map(|value| value.to_string_lossy().to_lowercase())
        .unwrap_or_default();

      files.push(ProjectFileEntry {
        relative_path,
        absolute_path: path.to_string_lossy().into_owned(),
        file_name,
        extension: extension.clone(),
        category: classify_extension(&extension).to_string(),
        size_bytes: metadata.len(),
        modified_at: metadata.modified().ok().and_then(system_time_to_iso),
      });
    }

    Ok(())
  }

  fn project_root(&self, record: &ProjectRecord) -> PathBuf {
    PathBuf::from(&record.root_path)
  }

  fn project_source_root(&self, record: &ProjectRecord) -> PathBuf {
    record
      .metadata
      .source_path
      .as_ref()
      .map(PathBuf::from)
      .unwrap_or_else(|| self.project_root(record))
  }

  pub fn load_chat_history(&self, project_id: Option<&str>) -> Result<Vec<ChatMessageRecord>, String> {
    let history_path = self.chat_history_path(project_id)?;
    if !history_path.exists() {
      return Ok(Vec::new());
    }
    let text = fs::read_to_string(&history_path).map_err(io_error)?;
    if text.trim().is_empty() {
      return Ok(Vec::new());
    }
    serde_json::from_str::<Vec<ChatMessageRecord>>(&text)
      .map_err(|error| format!("Chat-Verlauf konnte nicht gelesen werden: {error}"))
  }

  fn chat_history_path(&self, project_id: Option<&str>) -> Result<PathBuf, String> {
    match project_id.filter(|value| !value.trim().is_empty()) {
      Some(project_id) => {
        let project = self.get_project(project_id)?;
        let path = self.project_root(&project).join("chat").join("history.json");
        if let Some(parent) = path.parent() {
          fs::create_dir_all(parent).map_err(io_error)?;
        }
        Ok(path)
      }
      None => {
        let path = self.state_dir.join("chat").join("general.json");
        if let Some(parent) = path.parent() {
          fs::create_dir_all(parent).map_err(io_error)?;
        }
        Ok(path)
      }
    }
  }

  fn unique_slug(&self, name: &str) -> Result<String, String> {
    let base_slug = slugify(name);
    let mut slug = base_slug.clone();
    let mut counter = 2;
    let existing = self
      .load_registry()?
      .into_iter()
      .map(|project| project.slug)
      .collect::<std::collections::BTreeSet<_>>();
    while existing.contains(&slug) {
      slug = format!("{}-{}", base_slug, counter);
      counter += 1;
    }
    Ok(slug)
  }
}

fn metadata_from_inventory(source: &str, source_path: Option<String>, inventory: Option<&ProjectInventory>) -> ProjectMetadata {
  let mut metadata = ProjectMetadata {
    source: source.to_string(),
    source_path,
    attached: inventory.is_some(),
    ..ProjectMetadata::default()
  };

  if let Some(inventory) = inventory {
    metadata.inventory_path = Some(Path::new(&inventory.root_path).join("inventory.json").to_string_lossy().into_owned());
    metadata.file_count = inventory.summary.total_files;
    metadata.geodata_count = inventory.summary.geodata_files;
    metadata.document_count = inventory.summary.document_files;
    metadata.image_count = inventory.summary.image_files;
    metadata.qgis_count = inventory.summary.qgis_files;
    metadata.other_count = inventory.summary.other_files;
    metadata.scanned_at = Some(inventory.scanned_at.clone());
  }

  metadata
}

fn classify_extension(extension: &str) -> &'static str {
  match extension.to_lowercase().as_str() {
    "gpkg" | "shp" | "geojson" | "json" | "kml" | "kmz" | "csv" | "gdb" | "tif" | "tiff" => "geodata",
    "qgz" | "qgs" => "qgis",
    "doc" | "docx" | "pdf" | "rtf" | "odt" | "ppt" | "pptx" => "document",
    "txt" | "md" => "document",
    "png" | "jpg" | "jpeg" | "webp" | "svg" => "image",
    "zip" | "7z" | "rar" => "archive",
    _ => "other",
  }
}

fn resolve_workspace_root() -> PathBuf {
  let start = env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
  let mut candidate = start.canonicalize().unwrap_or(start);
  loop {
    if candidate.join("pyproject.toml").exists() || candidate.join("workspace").exists() {
      return candidate;
    }
    if !candidate.pop() {
      break;
    }
  }
  env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
}

fn now_iso() -> String {
  DateTime::<Utc>::from(std::time::SystemTime::now()).to_rfc3339()
}

fn system_time_to_iso(time: std::time::SystemTime) -> Option<String> {
  Some(DateTime::<Utc>::from(time).to_rfc3339())
}

fn normalize_tags(tags: &[String]) -> Vec<String> {
  let mut normalized = tags
    .iter()
    .map(|tag| tag.trim().to_string())
    .filter(|tag| !tag.is_empty())
    .collect::<Vec<_>>();
  normalized.sort();
  normalized.dedup();
  normalized
}

fn slugify(value: &str) -> String {
  let mut slug = value.trim().to_lowercase();
  for (source, target) in [("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")] {
    slug = slug.replace(source, target);
  }
  let mut result = String::new();
  let mut last_dash = false;
  for ch in slug.chars() {
    if ch.is_ascii_alphanumeric() {
      result.push(ch);
      last_dash = false;
    } else if !last_dash {
      result.push('-');
      last_dash = true;
    }
  }
  result.trim_matches('-').to_string().replace("--", "-")
}

fn uuid_hex() -> String {
  uuid::Uuid::new_v4().simple().to_string()
}

fn normalize_source_path(path: &Path) -> PathBuf {
  path.canonicalize().unwrap_or_else(|_| path.to_path_buf())
}

fn io_error(error: std::io::Error) -> String {
  error.to_string()
}

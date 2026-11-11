//! Where the catalogue, tool packs and icons are read from.
//!
//! The Rust crate and the Python package share one data directory,
//! `src/data`. With the default `bundled` feature it is
//! compiled into the binary (the Rust counterpart of shipping it in the wheel);
//! [`DataSource::Dir`] reads the same layout from disk instead, which is also how
//! a caller points the crate at their own catalogue.

use std::borrow::Cow;
use std::path::{Path, PathBuf};

#[cfg(feature = "bundled")]
static BUNDLED: include_dir::Dir<'static> = include_dir::include_dir!("$CONNECTOR_DATA_DIR");

/// A tree laid out like the bundled data: `connectors/`, `tools/`, `icons/`.
#[derive(Debug, Clone)]
pub enum DataSource {
    /// The data compiled into this crate (needs the `bundled` feature).
    Bundled,
    /// A directory on disk with the same layout.
    Dir(PathBuf),
}

impl Default for DataSource {
    fn default() -> Self {
        if cfg!(feature = "bundled") { Self::Bundled } else { Self::Dir(PathBuf::from("data")) }
    }
}

impl DataSource {
    /// Read one file by its path relative to the data root, e.g. `icons/slack.svg`.
    pub fn read(&self, rel: &str) -> Option<Cow<'static, [u8]>> {
        match self {
            #[cfg(feature = "bundled")]
            Self::Bundled => BUNDLED.get_file(rel).map(|f| Cow::Borrowed(f.contents())),
            #[cfg(not(feature = "bundled"))]
            Self::Bundled => None,
            Self::Dir(root) => std::fs::read(root.join(rel)).ok().map(Cow::Owned),
        }
    }

    pub fn exists(&self, rel: &str) -> bool {
        match self {
            #[cfg(feature = "bundled")]
            Self::Bundled => BUNDLED.get_file(rel).is_some(),
            #[cfg(not(feature = "bundled"))]
            Self::Bundled => false,
            Self::Dir(root) => root.join(rel).is_file(),
        }
    }

    /// Every `*.json` file under `rel_dir`, recursively, as sorted relative paths.
    pub fn json_files(&self, rel_dir: &str) -> Vec<String> {
        let mut out = Vec::new();
        match self {
            #[cfg(feature = "bundled")]
            Self::Bundled => {
                if let Some(dir) = BUNDLED.get_dir(rel_dir) {
                    collect_bundled(dir, &mut out);
                }
            }
            #[cfg(not(feature = "bundled"))]
            Self::Bundled => {}
            Self::Dir(root) => collect_disk(root, &root.join(rel_dir), &mut out),
        }
        out.sort();
        out
    }
}

#[cfg(feature = "bundled")]
fn collect_bundled(dir: &include_dir::Dir<'static>, out: &mut Vec<String>) {
    for file in dir.files() {
        if file.path().extension().is_some_and(|e| e == "json") {
            out.push(file.path().to_string_lossy().replace('\\', "/"));
        }
    }
    for sub in dir.dirs() {
        collect_bundled(sub, out);
    }
}

fn collect_disk(root: &Path, dir: &Path, out: &mut Vec<String>) {
    let Ok(entries) = std::fs::read_dir(dir) else { return };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            collect_disk(root, &path, out);
        } else if path.extension().is_some_and(|e| e == "json") {
            if let Ok(rel) = path.strip_prefix(root) {
                out.push(rel.to_string_lossy().replace('\\', "/"));
            }
        }
    }
}

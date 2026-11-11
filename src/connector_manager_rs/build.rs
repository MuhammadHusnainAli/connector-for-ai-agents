//! Point the crate at its data and documentation.
//!
//! In the repository both live outside the crate, shared with the Python
//! package: `../connector_manager/data` and `../../RUST.md`. A published crate
//! can only carry files inside its own folder, so `scripts/stage_crate.py`
//! copies them in (`data/`, `RUST.md`) before `cargo publish`. Whichever copy
//! exists is the one compiled in.

use std::path::{Path, PathBuf};

fn pick(manifest: &Path, staged: &str, shared: &str) -> PathBuf {
    let staged = manifest.join(staged);
    if staged.exists() { staged } else { manifest.join(shared) }
}

fn main() {
    let manifest = PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").expect("cargo sets CARGO_MANIFEST_DIR"));
    let data = pick(&manifest, "data", "../connector_manager/data");
    let docs = pick(&manifest, "RUST.md", "../../RUST.md");
    for path in [&data, &docs] {
        assert!(path.exists(), "missing {} -- run scripts/stage_crate.py, or build from the repository", path.display());
        println!("cargo:rerun-if-changed={}", path.display());
    }
    println!("cargo:rerun-if-changed=data");
    println!("cargo:rerun-if-changed=RUST.md");
    println!("cargo:rustc-env=CONNECTOR_DATA_DIR={}", data.display());
    println!("cargo:rustc-env=CONNECTOR_DOCS={}", docs.display());
}

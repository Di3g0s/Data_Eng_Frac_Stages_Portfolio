# Treatment workbooks and CSV provenance

This is a **single-repository** portfolio. The existing Excel and CSV files are retained in their original relative paths, and the in-place upgrade **never edits, deletes, moves, regenerates, or untracks them**.

| Existing path in this repository | Role |
|---|---|
| `WITS_starter/data/raw/16B(78)-32_Stage 1_Treatment Data.xlsx` | Original Stage 1 source workbook |
| `WITS_starter/data/raw/16B(78)-32_Stage 2_Treatment Data.xlsx` | Original Stage 2 source workbook |
| `WITS_starter/data/prepared/canonical.csv` | Legacy canonical data used in earlier experiments |
| `WITS_starter/canonical_header.csv` | Canonical CSV schema header |

The installer first computes SHA-256 hashes for every `.csv`, `.xls`, `.xlsx`, and `.xlsm` file under the repository (excluding virtual environments and Git internals), and checks them again after applying documentation and code updates. If a required source file is missing, installation is refused. Neither the installer nor the `.gitignore` adds rules excluding these data directories.

## Data lineage note

`data/prepared/canonical.csv` is the **original legacy output**, not a regenerated dataset. The improved `data/raw_2_prepared.py` adapter correctly records the physical Excel source row and derives the stage from its workbook filename. These differences can change stable sample IDs. For reproducibility, do not mix old and new manifests without documenting which adapter version produced them.

Create any newly prepared per-stage CSV under its own name (for example `stage1.csv`, `stage2.csv`), and review it before checking it into the same Git repository. The adapter refuses to overwrite existing files unless explicitly authorized.

## Public data and rights

The repository is public. Before publishing additional or revised source measurements, confirm redistribution permissions and remove any confidential operational information. Git history preserves older versions even after a later deletion.

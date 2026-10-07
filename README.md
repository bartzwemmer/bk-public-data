# Eindhoven Wildflower Dataset Tools

This folder contains Python tools for downloading, visualizing, and filtering the [Eindhoven Wildflower Dataset](https://doi.org/10.34894/U4VQJ6) from DataverseNL.

The dataset consists of **2,002 high-resolution photos** (6720 × 4480 pixels, ~28 GB total) of 1m² ground patches and **2,002 Pascal VOC XML annotation files** (>65,000 bounding boxes across 160 wildflower species) collected in Eindhoven, The Netherlands.

---

## Prerequisites

No global Python installation is required. Run all scripts using [`uv`](https://docs.astral.sh/uv/):

```powershell
# Verify uv is installed
uv --version
```

---

## 1. Dataset Downloader (`download_dataset.py`)

[download_dataset.py](file:///G:/My%20Drive/OGL/Berenklauw/public-data/Eindhoven%20Wildflower%20Dataset/download_dataset.py) connects to the DataverseNL REST API, iterates through the dataset's files page-by-page (matching the 10-item pagination on the web interface), and downloads them with integrity checks.

### Features
- **Anti-Bot Bypass**: Transparently solves DataverseNL's Anubis SHA-256 proof-of-work challenge in [`DataverseClient._solve_anubis`](file:///G:/My%20Drive/OGL/Berenklauw/public-data/Eindhoven%20Wildflower%20Dataset/download_dataset.py#L42) and preserves session cookies.
- **Page-by-Page Batches**: Slices the 4,004 files into 401 pages of 10 files each.
- **Resumable Downloads**: In [`download_file`](file:///G:/My%20Drive/OGL/Berenklauw/public-data/Eindhoven%20Wildflower%20Dataset/download_dataset.py#L114), existing files with matching file sizes are automatically skipped.
- **Atomic File Writing**: Files stream into `.part` temporary files and only rename upon complete download to prevent corrupt partial files.
- **Integrity Verification**: Verifies streaming SHA-1 checksums against the official Dataverse hashes.
- **Zero Dependencies**: Uses only standard Python library modules (`urllib`, `hashlib`, `json`, `pathlib`, `argparse`).

### Usage Examples

```powershell
# 1. Download all 401 pages (all 4,004 files)
uv run python download_dataset.py

# 2. Dry run: inspect pages and files without downloading
uv run python download_dataset.py --dry-run --start-page 1 --end-page 3

# 3. Download a specific range of pages (e.g. pages 1 to 5 = 50 files)
uv run python download_dataset.py --start-page 1 --end-page 5

# 4. Download only XML annotation files (skipping large images)
uv run python download_dataset.py --file-type xml

# 5. Download only JPG images
uv run python download_dataset.py --file-type jpg

# 6. Custom page/batch size (e.g. 20 files per batch)
uv run python download_dataset.py --page-size 20 --end-page 2

# 7. Save to a custom folder
uv run python download_dataset.py --target-dir "D:\Data\Wildflowers"
```

### Options Reference

| Argument | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `--url` | string | `doi:10.34894/U4VQJ6` | Dataverse web URL or persistentId. |
| `--target-dir`, `-d` | path | `.` | Destination directory for downloaded files. |
| `--page-size`, `-s` | int | `10` | Number of files per page/batch. |
| `--start-page` | int | `1` | 1-based page number to start from. |
| `--end-page` | int | `None` (all) | 1-based page number to stop at. |
| `--file-type` | choice | `all` | Filter by file type: `all`, `jpg`, or `xml`. |
| `--delay` | float | `0.2` | Polite pause (seconds) between file requests. |
| `--skip-checksum` | flag | `False` | Disables SHA-1 checksum verification. |
| `--dry-run` | flag | `False` | Simulates the download without writing files. |

---

## 2. Annotation Visualizer (`visualize_annotation.py`)

[visualize_annotation.py](file:///G:/My%20Drive/OGL/Berenklauw/public-data/Eindhoven%20Wildflower%20Dataset/visualize_annotation.py) renders Pascal VOC bounding box annotations on high-resolution wildflower images.

### Features
- **VOC XML Parser**: In [`parse_voc_xml`](file:///G:/My%20Drive/OGL/Berenklauw/public-data/Eindhoven%20Wildflower%20Dataset/visualize_annotation.py#L42), extracts all `<object>` tags, species names, and `<bndbox>` coordinates.
- **Adaptive Rendering**: In [`draw_annotations`](file:///G:/My%20Drive/OGL/Berenklauw/public-data/Eindhoven%20Wildflower%20Dataset/visualize_annotation.py#L94), draws high-contrast colored bounding boxes with semi-transparent species badges, scaled for high-resolution images.
- **1:1 Native Resolution Zoom**: Uses [`find_dense_crop_region`](file:///G:/My%20Drive/OGL/Berenklauw/public-data/Eindhoven%20Wildflower%20Dataset/visualize_annotation.py#L74) to locate a dense cluster of flowers and creates a side-by-side comparison between the raw pixels and the ground truth annotations.
- **Overview Export**: Produces an optimized 2000px wide overview of the full 1m² scene for viewing without image viewer lag.

### Usage Examples

```powershell
# Visualize default image and XML in the folder
uv run --with pillow python visualize_annotation.py

# Specify an image and XML pair
uv run --with pillow python visualize_annotation.py --image "20210402104347-Urban.jpg" --xml "20210402104347-Urban.xml"

# Save outputs to a specific directory
uv run --with pillow python visualize_annotation.py --image "20210402102531-Urban.jpg" --xml "20210402102531-Urban.xml" --output-dir "visualizations"
```

### Generated Files
- `*_annotated_overview.jpg`: Downscaled (2000px) full-scene overview displaying all flower annotations.
- `*_zoom_comparison.jpg`: Side-by-side comparison showing raw camera pixels at 100% native resolution alongside the ground truth bounding boxes.

### Options Reference

| Argument | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `--image` | path | `20210402102531-Urban.jpg` | Path to the JPG image file. |
| `--xml` | path | `20210402102531-Urban.xml` | Path to the Pascal VOC XML file. |
| `--output-dir` | path | `.` | Directory where output images are saved. |

---

## 3. Dataset Filtering & Pipeline (`filter_downloaded_datasets.py`)

[filter_downloaded_datasets.py](file:///G:/My%20Drive/OGL/Berenklauw/public-data/Eindhoven%20Wildflower%20Dataset/filter_downloaded_datasets.py) filters downloaded annotations using DuckDB to identify images containing target species, copies relevant image and XML pairs, and generates visualizations.

### Features
- **Fast XML Querying with DuckDB**: Uses DuckDB's community `webbed` extension to parse and query Pascal VOC XML files across `data/*.xml` directly via SQL without loading full XML trees into memory.
- **Species Filtering**: Queries for specific target species (by default: *Arctium lappa*, *Heracleum sphondylium*, and *Anthriscus sylvestris*).
- **Automated Asset Extraction**: Copies matching `.xml` annotations and corresponding `.jpg` images from `data/` to `visualized_data/`.
- **Integrated Visualization**: Invokes [`visualize`](file:///G:/My%20Drive/OGL/Berenklauw/public-data/Eindhoven%20Wildflower%20Dataset/visualize_annotation.py#L160) from [`visualize_annotation.py`](file:///G:/My%20Drive/OGL/Berenklauw/public-data/Eindhoven%20Wildflower%20Dataset/visualize_annotation.py) to automatically produce overview and zoom comparison images for all matching files.

### Usage Examples

```powershell
# Filter datasets and generate visualizations
uv run python filter_downloaded_datasets.py
```

> [!NOTE]
> This step assumes the downloaded images and XML files are located in `data/` (for example, by running `download_dataset.py --target-dir data`). Matching assets and their rendered visualization images are placed into `visualized_data/`.

---

## TO DO
The filtered datasets need to be transformed, including their annotation, to be able to use in a YOLO26 training run as hard negatives.

## Dataset Citation

```bibtex
@data{U4VQJ6_2024,
  author    = {Gerard Schouten and Bas S.H.T. Michielsen and Barbara Gravendeel},
  publisher = {DataverseNL},
  title     = {Eindhoven Wildflower Dataset},
  year      = {2024},
  doi       = {10.34894/U4VQJ6},
  url       = {https://doi.org/10.34894/U4VQJ6}
}
```

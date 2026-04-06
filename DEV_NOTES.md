# DEV_NOTES.md - Technical Documentation

This document provides in-depth technical details about Font Enhancer for developers, contributors, and AI agents. It covers architecture, algorithms, data structures, and extension points.

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture](#architecture)
3. [Kerning Engine](#kerning-engine)
4. [Preview Renderer](#preview-renderer)
5. [GUI Implementation](#gui-implementation)
6. [Data Structures](#data-structures)
7. [Extension Points](#extension-points)
8. [Dependencies](#dependencies)
9. [Testing](#testing)
10. [Coding Standards](#coding-standards)

---

## Project Overview

**Font Enhancer** is a Linux-native desktop application for automated font kerning. It targets type designers who use FontForge and need to automate the repetitive task of setting kerning pairs.

### Goals

- **Zero proprietary dependencies**: All components must be open-source
- **FontForge integration**: Seamless UFO round-trip workflow
- **Live preview**: Real-time kerning visualization
- **Extensibility**: Prepare for additional font polishement tools

### Non-Goals

- Full OpenType feature editing (out of scope for v1)
- Cloud processing (completely offline)
- Windows/macOS native builds (Linux-first)

---

## Architecture

```
font-enhancer/
├── main.py              # Application entry, CLI args, logging setup
├── gui.py               # PyQt6 MainWindow and UI components
├── kerner.py            # Auto-kerning algorithm
├── preview_renderer.py  # Freetype rendering
├── run.sh               # Launcher script using uv
├── requirements.txt     # Python dependencies (UV compatible)
├── README.md            # User-facing documentation
└── DEV_NOTES.md         # This file
```

### Module Dependencies

```
main.py
  └─> gui.py
       ├─> kerner.py (auto_kern, KerningResult)
       └─> preview_renderer.py (PreviewFontFace, PreviewRenderer)
```

### CLI Usage

```bash
# Interactive mode
python main.py

# Open UFO font directly
python main.py --font=/path/to/font.ufo/

# Open and auto-kern
python main.py --font=/path/to/font.ufo/ --auto-kern

# Specify test string
python main.py --font=/path/to/font.ufo/ --preview="Hello World"

# Export after processing
python main.py --font=/path/to/font.ufo/ --export=/output/font.otf
```

### Command Line Arguments

| Argument | Description |
|----------|-------------|
| `--font`, `-f` | Path to UFO font directory |
| `--auto-kern`, `-k` | Auto-run kerning after load |
| `--export` | Export path (UFO or OTF) |
| `--preview` | Test string for preview |

---

## Kerning Engine (`kerner.py`)

### Core Algorithm

The auto-kerning engine uses a **class-based kerning** approach:

1. **Metric Extraction**: For each glyph with contours, extract:
   - Left sidebearing (distance from x=0 to leftmost contour)
   - Right sidebearing (distance from rightmost contour to advance width)
   - Advance width
   - Bounding box
   - Contour area (approximated)

2. **Glyph Classification**: Group glyphs into left-classes and right-classes:
   - Use template classes as seeds (e.g., "O_left", "V_left")
   - Compute weighted Euclidean distance between metric profiles
   - Assign unclassified glyphs to nearest class within threshold
   - Create new classes for outliers

3. **Kern Value Calculation**: For each class pair:
   - Compute class centroid (average metrics)
   - Calculate visual gap: `gap = right.left_sb - left.right_sb`
   - Apply heuristic: `kern = -gap * size_factor`
   - Clamp to user-defined range (default: -200 to +200 units)

4. **Pair Expansion**: Convert class pairs to individual glyph pairs:
   - A class pair like (O_left, A_right) expands to all (O, A), (C, A), (Q, A)...

### Key Functions

```python
def extract_metrics(glyph: Glyph) -> GlyphMetrics
    """Extract sidebearings, advance width, bounding box from a glyph."""

def cluster_glyphs(
    metrics: dict[str, GlyphMetrics],
    threshold: float = 0.35,
    templates: Optional[dict[str, list[str]]] = None,
) -> dict[str, list[str]]
    """Group glyphs into classes by metric similarity."""

def compute_pair_kern(
    left: GlyphMetrics,
    right: GlyphMetrics,
    min_kern: float = -200,
    max_kern: float = 200,
) -> float
    """Calculate optimal kern value for a glyph pair."""

def compute_class_kerning(...) -> list[ClassKernPair]
    """Compute kerning values for every class combination."""

def auto_kern(
    font: Font,
    min_kern: float = -200,
    max_kern: float = 200,
    strength: float = 1.0,
    ...
) -> KerningResult
    """Full auto-kerning pipeline."""
```

### Templates

The engine includes template classes for common Latin shapes:

```python
LATIN_LEFT_CLASSES = {
    "O_left": ["O", "C", "Q", "G", "D", ...],
    "V_left": ["V", "W", "Y", ...],
    ...
}

LATIN_RIGHT_CLASSES = {
    "O_right": ["O", "C", "Q", "G", ...],
    "V_right": ["V", "W", "Y", ...],
    ...
}
```

These can be extended for additional scripts (Arabic, Cyrillic, Greek) by creating new template dictionaries.

---

## Preview Renderer (`preview_renderer.py`)

### Rendering Pipeline

1. **Font Loading**:
   - Load `.otf`/`.ttf` directly via `freetype-py`
   - Load `.ufo` by compiling to temporary TTF using `ufo2ft`

2. **Text Rendering** (freetype-py):
   - Set font size (in points)
   - Iterate through characters and load each glyph
   - Get glyph advance and bitmap
   - Convert FT bitmap to QImage

3. **Color Composition**:
   - Create ARGB32 QImage
   - Use Qt painter with CompositionMode_SourceIn to tint glyphs

4. **Note on Harfbuzz**:
   - Harfbuzz integration was removed due to API compatibility issues
   - Basic LTR rendering works with simple character iteration
   - RTL/Arabic shaping would require additional setup

### Key Classes

```python
class PreviewFontFace:
    """Wraps freetype face for rendering."""
    
    @classmethod
    def from_file(cls, path: str) -> "PreviewFontFace"
        """Load compiled font (.otf/.ttf)."""
    
    @classmethod
    def from_ufo(cls, ufo_path: str) -> "PreviewFontFace"
        """Compile UFO to TTF, then load."""

class PreviewRenderer:
    """High-level renderer for text preview."""
    
    @property
    def kern_pairs: dict[tuple[str, str], float]
    
    @property
    def kern_strength: float  # -1.0 to 1.0
    
    @property
    def font_size: float
    
    def render(...) -> QImage
        """Render text to QImage."""
    
    def render(...) -> QImage
        """Shape and render text to QImage."""
```

### RTL & Complex Scripts

The preview renderer uses harfbuzz for shaping, which handles:

- **RTL scripts**: Arabic, Hebrew, Persian, Urdu
- **Tifinagh**: Berber script
- **Complex joining**: Arabic, Devanagari
- **OpenType features**: liga, dlig, calt, kern

**Important limitation**: The auto-kerner only adjusts basic pair spacing via the `kern` table. Complex contextual shaping (rlig, init, medi, fina, mark, mkmk) is rendered correctly by harfbuzz but not kerned by our engine. Full GPOS-based contextual kerning is out of scope for v1.

---

## GUI Implementation (`gui.py`)

### Layout

```
┌─────────────────────────────────────────────────────────────┐
│ Menu Bar (File > Open UFO..., Exit)                        │
├─────────────┬───────────────────────────────────────────────┤
│ Left Panel  │                                               │
│ ┌─────────┐ │                                               │
│ │ Font    │ │            Preview Area                       │
│ │ Controls│ │         (Rendered Text)                       │
│ └─────────┘ │                                               │
│ ┌─────────┐ │                                               │
│ │ Kerning │ │                                               │
│ │ Controls│ │                                               │
│ └─────────┘ │                                               │
│ ┌─────────┐ │                                               │
│ │ Preview │ │                                               │
│ │ Controls│ │                                               │
│ └─────────┘ │                                               │
│ ┌─────────┐ │                                               │
│ │ Classes │ │                                               │
│ └─────────┘ │                                               │
│ ┌─────────┐ │                                               │
│ │ Export  │ │                                               │
│ └─────────┘ │                                               │
│ ┌─────────┐ │                                               │
│ │ Log     │ │                                               │
│ └─────────┘ │                                               │
├─────────────┴───────────────────────────────────────────────┤
│ Status Bar                                                  │
└─────────────────────────────────────────────────────────────┘
```

### Components

| Component | Type | Purpose |
|-----------|------|---------|
| `open_btn` | QPushButton | Opens UFO directory |
| `auto_kern_btn` | QPushButton | Triggers kerning computation |
| `strength_slider` | QSlider | Adjusts kern strength (-1.0 to 1.0) |
| `reset_btn` | QPushButton | Reverts to original kerning |
| `test_string_combo` | QComboBox | Selects/edits test string |
| `direction_combo` | QComboBox | LTR or RTL |
| `guides_check` | QCheckBox | Toggle guide visibility |
| `classes_list` | QListWidget | Shows glyph classes |
| `export_ufo_btn` | QPushButton | Export kerned UFO |
| `export_otf_btn` | QPushButton | Export compiled OTF |
| `log_text` | QTextEdit | Application log |

### Signals

- `open_font()` - Load UFO via QFileDialog
- `run_auto_kern()` - Start background kerning thread
- `on_strength_changed(value)` - Update kern strength, refresh preview
- `on_guides_toggled(checked)` - Toggle guide overlay
- `reset_kerning()` - Revert kerning to original
- `update_preview()` - Re-render preview area
- `export_ufo()` - Save kerned UFO
- `export_otf()` - Compile and save OTF

### Background Processing

The auto-kerning runs in a `QThread` to keep the UI responsive:

```python
class KerningWorker(QThread):
    finished = pyqtSignal(KerningResult)
    error = pyqtSignal(str)
    
    def run(self):
        # Compute kerning in background
        result = auto_kern(font, ...)
        self.finished.emit(result)
```

### Theme Detection

The GUI detects system theme and adapts colors:

```python
is_dark = palette.color(QPalette.ColorRole.Window).lightness() < 128
bg_color = QColor(30, 30, 30) if is_dark else QColor(245, 245, 245)
fg_color = QColor(255, 255, 255) if is_dark else QColor(20, 20, 20)
```

---

## Data Structures

### KerningResult

```python
@dataclass
class KerningResult:
    left_classes: dict[str, list[str]]           # "O_left": ["O", "C", "Q", ...]
    right_classes: dict[str, list[str]]         # "A_right": ["A", "N", "M", ...]
    class_pairs: list[ClassKernPair]            # [(O_left, A_right, -30), ...]
    glyph_pairs: dict[tuple[str, str], float]  # {(O, A): -30, (C, A): -28, ...}
    metrics: dict[str, GlyphMetrics]             # {"A": GlyphMetrics(...), ...}
```

### GlyphMetrics

```python
@dataclass
class GlyphMetrics:
    name: str
    left_sb: float          # Left sidebearing
    right_sb: float         # Right sidebearing
    advance_width: float    # Total advance width
    bbox: tuple[float, float, float, float]  # (xmin, ymin, xmax, ymax)
    contour_area: float     # Approximate area (bbox width * height)
    has_contours: bool      # True if glyph has outlines
```

### ClassKernPair & KernPair

```python
@dataclass
class ClassKernPair:
    left_class: str
    right_class: str
    value: float           # Kern adjustment in font units

@dataclass
class KernPair:
    left_glyph: str
    right_glyph: str
    value: float
```

---

## Extension Points

### Adding New Script Support

1. **Define template classes** in `kerner.py`:

```python
ARABIC_LEFT_CLASSES = {
    "Alef_left": ["Alef", "Lam", "Noon", ...],
    ...
}

ARABIC_RIGHT_CLASSES = {
    "Alef_right": ["Alef", "Lam_alef", ...],
    ...
}
```

2. **Add UI selector** in `gui.py`:

```python
self.script_combo = QComboBox()
self.script_combo.addItems(["Latin", "Arabic", "Cyrillic"])
```

3. **Pass templates** to `auto_kern()`:

```python
auto_kern(font, left_templates=ARABIC_LEFT_CLASSES, ...)
```

### Adding New Features

1. **Glyph Outfit Editor**: Add manual sidebearing adjustment UI
2. **Hinting Automation**: Use `ttfautohint` integration
3. **Metrics Checking**: Compare stem widths across glyphs
4. **Batch Processing**: Iterate over multiple UFO directories

### Hook System

Future versions may implement a plugin system:

```python
class FontEnhancerPlugin:
    name: str
    version: str
    
    def process_font(self, font: Font) -> Font:
        """Called after auto-kern, before export."""
        ...
```

---

## Dependencies

### Python (see `requirements.txt`)

| Package | Purpose | License |
|---------|---------|---------|
| PyQt6 | GUI framework | GPLv3 (commercial license available) |
| fonttools | Font manipulation | MIT |
| ufoLib2 | UFO format handling | MIT |
| defcon | Glyph data structures | MIT |
| freetype-py | Font rasterization | FreeType License |
| uharfbuzz | Text shaping | MIT |
| ufo2ft | UFO to OTF/TTF compilation | Apache 2.0 |
| booleanOperations | Boolean path ops | MIT |
| cu2qu | Cubic to quadratic conversion | Apache 2.0 |
| compreffor | Compressed glyph outlines | Apache 2.0 |

### System (Linux)

| Library | Ubuntu Package | Fedora Package |
|---------|---------------|----------------|
| FreeType | libfreetype6-dev | freetype-devel |
| HarfBuzz | libharfbuzz-dev | harfbuzz-devel |
| OpenGL | libgl1-mesa-glx | mesa-libGL |
| XKB | libxkbcommon-x11-0 | libxkbcommon-x11 |

---

## Testing

### Manual Testing

1. **Load UFO**: Open a UFO font exported from FontForge
2. **Run Auto-Kern**: Click button, verify no errors
3. **Adjust Strength**: Slide from 0 to 1.0, verify preview updates
4. **Export UFO**: Save, verify UFO is valid
5. **Export OTF**: Save, verify font is usable

### Test Fonts

Use these public domain test fonts:

- **Roboto** (Google Fonts) - Basic Latin
- **Noto Sans** (Google Fonts) - Extensive script support
- **Source Serif Pro** - Serif kerning test

### Automated Tests

Future: Add pytest-based tests:

```python
def test_metric_extraction():
    font = ufoLib2.Font.open("test.ufo")
    glyph = font["A"]
    metrics = extract_metrics(glyph)
    assert metrics.advance_width > 0

def test_kern_calculation():
    left = GlyphMetrics("T", left_sb=50, right_sb=100, advance_width=600, ...)
    right = GlyphMetrics("A", left_sb=80, right_sb=80, advance_width=600, ...)
    kern = compute_pair_kern(left, right)
    assert -200 <= kern <= 200
```

---

## Coding Standards

### Style

- Follow **PEP 8** with 100 character line limit
- Use **type hints** for all function signatures
- Use **dataclasses** for structured data
- Use **docstrings** for all public functions

### Naming

- `snake_case` for functions, methods, variables
- `PascalCase` for classes, data classes
- `SCREAMING_SNAKE_CASE` for constants

### Imports

```python
# Standard library
import os
import sys
from typing import Optional

# Third-party
from PyQt6.QtWidgets import QApplication, QMainWindow
import ufoLib2

# Local
from kerner import auto_kern, KerningResult
from preview_renderer import PreviewFontFace
```

### Error Handling

- Log errors with context: `logger.error(f"Failed to load font: {e}")`
- Show user-friendly messages via QMessageBox
- Never crash on malformed input

### Performance

- Run heavy computation in background threads
- Cache glyph metrics after extraction
- Use `QTimer` for debounced preview updates

---

## Quick Reference

| Task | Code Location |
|------|---------------|
| Load UFO font | `ufoLib2.Font.open(path)` |
| Extract glyph metrics | `kerner.extract_metrics(glyph)` |
| Run auto-kerning | `kerner.auto_kern(font)` |
| Render text preview | `PreviewRenderer.render(text, width, height)` |
| Apply kern strength | `renderer.kern_strength = value` |
| Export UFO | `font.save(out_dir)` |
| Export OTF | `compileOTF(font).save(out_path)` |

---

## Contact & Contributing

- **Issues**: https://github.com/anomalyco/font-enhancer/issues
- **Discussions**: https://github.com/anomalyco/font-enhancer/discussions
- **License**: MIT (see LICENSE file)

---

*Last updated: 2026-04-06*

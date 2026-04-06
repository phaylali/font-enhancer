# Font Enhancer

A fully open-source, Linux-native desktop application for automated font kerning with live preview. Built for type designers who want to streamline their workflow with FontForge.

![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)
![Platform: Linux](https://img.shields.io/badge/Platform-Linux-blue.svg)
![Python: 3.10+](https://img.shields.io/badge/Python-3.10+-orange.svg)

## Overview

Font Enhancer automates the kerning process for fonts by:

1. **Loading UFO fonts** from FontForge's standard export format
2. **Auto-classifying glyphs** by metric similarity (left/right sidebearings, advance widths)
3. **Computing optimal kern values** using weighted heuristics
4. **Providing live preview** with real-time adjustment
5. **Exporting back to UFO** for re-import into FontForge, or to OTF for final build

## Features

- **Auto-Kerning Engine**: Class-based kerning using glyph metrics
- **Live Preview**: Real-time rendering with Freetype
- **RTL Support**: Arabic, Tifinagh, and other complex scripts
- **Strength Slider**: Adjust kerning intensity in real-time
- **Guide Toggle**: Visualize sidebearings and kern pairs
- **FontForge Integration**: Seamless UFO round-trip workflow
- **CLI Support**: Run from command line with options

## Quick Start

### 1. Install Dependencies

```bash
# Using uv (recommended)
./run.sh

# Or manually:
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

### 2. Run the Application

```bash
# Interactive mode
python main.py

# Or use the launcher script
./run.sh
```

### 3. Command Line Options

```bash
# Open UFO font directly
./run.sh --font=/path/to/font.ufo/

# Open and auto-kern
./run.sh --font=/path/to/font.ufo/ --auto-kern

# Specify test string
./run.sh --font=/path/to/font.ufo/ --preview="Hello World"
```

## FontForge Workflow

1. **Export your font as UFO** from FontForge:
   - In FontForge: `File > Generate Fonts...`
   - Select "UFO (format 3) font" as output format
   - Choose a directory (e.g., `MyFont.ufo/`)

2. **Open in Font Enhancer**:
   - Click "Open UFO Font..."
   - Select the `.ufo` directory

3. **Run Auto-Kern**:
   - Click "Run Auto-Kern" to compute kerning pairs
   - Use the strength slider to adjust intensity
   - Preview with different test strings

4. **Export and Re-import**:
   - Click "Export UFO" to save the kerned version
   - Back in FontForge: `File > Import...` and select the UFO
   - Generate your final OTF/TTF

## Requirements

### System Dependencies (Linux)

**Ubuntu/Debian:**
```bash
sudo apt-get update
sudo apt-get install -y \
    python3-dev \
    python3-pip \
    libfreetype6-dev \
    libgl1-mesa-glx \
    libxkbcommon-x11-0 \
    libdbus-1-3
```

**Fedora:**
```bash
sudo dnf install -y \
    python3-devel \
    freetype-devel \
    mesa-libGL \
    libxkbcommon-x11
```

### Python Dependencies

See `requirements.txt` for the full list. Key dependencies:

- **PyQt6** - GUI toolkit
- **fonttools** - Font manipulation
- **ufoLib2** - UFO format handling
- **defcon** - Glyph data structures
- **freetype-py** - Font rasterization
- **ufo2ft** - UFO to OTF/TTF compilation

## Usage Guide

### Test Strings

The app includes preset test strings optimized for kerning detection:
- `Hamburgefonts` - Classic kerning test
- `AVAVAWAWA` - A/V/W alternation
- `Wave WAVY` - W and A pairs
- `To To To` - Repetition tests

### Kerning Strength

- **1.0** (default): Full auto-kern values
- **0.5**: Half strength for subtle adjustments
- **-0.5 to -1.0**: Invert kerning (for debugging)

### Keyboard Shortcuts

- `Ctrl+O` - Open UFO font
- `Ctrl+Q` - Exit application

## Architecture

```
font-enhancer/
├── main.py              # Entry point
├── gui.py               # PyQt6 interface
├── kerner.py            # Auto-kerning engine
├── preview_renderer.py  # Freetype rendering
├── run.sh               # Launcher script (uses uv)
├── requirements.txt     # Python dependencies
├── README.md            # This file
└── DEV_NOTES.md         # Technical documentation
```

## License

MIT License - See LICENSE file for details.

## Contributing

Contributions welcome! Please read DEV_NOTES.md for technical details.

## Future Features

Planned enhancements for future versions:

1. **Glyph Outfit Editor** - Adjust sidebearings manually
2. **Hinting Automation** - Automatic instruction generation
3. **Metrics Checking** - Verify uniform stem widths
4. **OpenType Feature Editor** - Manage liga, kern, calt features
5. **Batch Processing** - Process multiple fonts at once
6. **Google Fonts Checklist** - Validate fonts for submission

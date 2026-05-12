# ISSUES.md — Font Enhancer Known Issues

Auto-generated from debugging sessions. All issues verified against actual project code.

---

## Issue 1: Exported OTF Has No Kerning Table

**Severity:** Critical  
**Status:** ✅ Fixed  

**Symptom:** 292,938 kern pairs are generated (visible in Log panel), but the exported `.otf` file has no kerning lookup table when opened in FontForge or tested in FontDrop.

**Root Cause:** `gui.py:461–486` — `export_otf()` re-opens the font from disk (`ufoLib2.Font.open(self.font_path)`) which is the **original unmodified file**. It then tries to copy kerning from `self.font.kerning`, but `self.font` (the in-memory GUI font) is **never updated** with the kerning results.

The `KerningWorker` (gui.py:52–76) runs on a background thread and calls `auto_kern(font, ...)` which modifies a **separate** font object. That modified font stays inside the worker thread and is never propagated back to `MainWindow.font`.

**Code path (broken):**
```
KerningWorker.run() → auto_kern(worker_font) → worker_font now has kerning
                                                  ↓ (never copied back)
MainWindow.font → still has NO kerning
                                                  ↓
export_otf() → re-reads from disk (no kerning) 
             → copies from self.font.kerning (empty)
             → exports zero-kerning OTF
```

**Location:** `gui.py:472–476`

**Fix applied:** `_on_kerning_finished` now writes all computed glyph pairs directly into `self.font.kerning` after the worker thread completes. `on_strength_changed` keeps `self.font.kerning` in sync whenever the slider moves. `export_otf()` copies from `self.font.kerning` (which now has data) into the freshly opened disk copy before compilation. A defensive fallback re-applies from `KerningResult.glyph_pairs` if `self.font.kerning` is unexpectedly empty.

---

## Issue 2: Preview Shows Boxes Instead of Letters

**Severity:** High  
**Status:** ✅ Fixed  

**Symptom:** The live preview renders empty rectangles (`.notdef` glyphs) instead of actual letterforms.

**Root Cause:** The `PreviewFontFace.from_ufo()` method (`preview_renderer.py:69–89`) compiles the UFO to a temporary TTF using `ufo2ft.compileTTF()`. If the FontForge UFO export produces quadratic Bézier outlines or has missing glyph order/cmap data, `ufo2ft` compilation produces a TTF with broken or empty glyphs.

**Contributing factors:**
- FontForge may export outlines in a format `ufo2ft` cannot cleanly convert
- Missing or malformed `public.glyphOrder` in the UFO
- `ufo2ft.compileTTF()` called with no conversion options (no `removeOverlaps`, `decomposeComponents`, etc.)

**Location:** `preview_renderer.py:69–89`

**Fix applied:** `PreviewFontFace.from_ufo()` now calls `compileTTF(ufo, removeOverlaps=True, decomposeComponents=True)`. This resolves overlapping path and composite glyph issues from FontForge exports.

---

## Issue 3: No Kerning Pairs Extracted (Empty Metrics)

**Severity:** High  
**Status:** ✅ Fixed  

**Symptom:** "Generated 0 kern pairs" in Log despite a valid-looking UFO being loaded.

**Root Cause:** `kerner.py:406–411` requires `font.layers["public.default"]` to exist. If the FontForge UFO export doesn't properly populate the `public.default` layer (or stores glyphs in a non-standard layer structure), the metrics extraction loop silently produces an empty dict and returns an empty `KerningResult`.

**Location:** `kerner.py:406–414`

```python
layer = font.layers.get("public.default", None)
if layer:  # If layer is None or empty, this is silently skipped
    for glyph_name in layer.keys():
        ...
```

**No error or warning is emitted** when this happens.

**Fix applied:** `auto_kern()` now checks if `public.default` is `None` or empty, logs all available layer names as a warning, then iterates available layers to find the first non-empty one as a fallback. When no metrics are found at all, a descriptive warning message is emitted explaining the possible causes.

---

## Issue 4: No Direct OTF/TTF Import Support

**Severity:** Medium  
**Status:** ✅ Fixed  

**Symptom:** Users with compiled `.otf` or `.ttf` files cannot load them into the application.

**Details:** The GUI file dialog (`gui.py:314–316`) and CLI `--font` argument (`main.py:39`) only support directory-based UFO paths. The `PreviewFontFace` class has a `from_file()` method for compiled fonts, but `gui.py` never calls it — `load_font_from_path()` and `open_font()` both call `ufoLib2.Font.open()` which only handles UFO directories.

**Impact:** Users must always export UFO from FontForge first, even if they already have a compiled font.

**Location:** `gui.py:285–340`

**Fix applied:** Added `open_compiled_font()` method and a `File > Open OTF/TTF (preview-only)...` menu entry (`Ctrl+Shift+O`). `load_font_from_path()` (CLI entry point) also detects `.otf`/`.ttf` extensions and routes to the compiled-font loader. In compiled-font mode, the kerning engine, UFO export, and OTF export buttons are disabled with a clear log message explaining why.

---

## Issue 5: FontForge UFO Export Settings Confusion

**Severity:** Low  
**Status:** User-facing confusion  

**Symptom:** FontForge offers multiple UFO export options ("Unified Font Object (UFO3)", "Unified Font Object 3", etc.) with no clear indication of which to choose. Wrong settings can silently produce a broken UFO.

**Details:** Users reported seeing both "Unified Font Object (UFO3)" and "Unified Font Object 3" in the format dropdown. Both are valid labels for the same UFO3 format, but other options like "UFO" (v2) or "Decomposed" outlines cause failures downstream.

**Location:** N/A (FontForge UI, not project code)

**Fix:** Document the exact settings in the README (already partially done in the FontForge Workflow section).

---

## Issue 6: `ufo2ft` Compilation Options Not Configured

**Severity:** Medium  
**Status:** ✅ Fixed  

**Symptom:** Potentially contributes to Issue 2 (broken preview).

**Details:** Both `compileTTF` (preview_renderer.py:79) and `compileOTF` (gui.py:477) are called with only the font object and no additional options:

```python
ttf = compileTTF(ufo)      # no options
otf = compileOTF(font)     # no options
```

`ufo2ft` supports several keyword arguments that could resolve outline compatibility issues:
- `removeOverlaps` — handles overlapping paths FontForge may export
- `decomposeComponents` — breaks composite glyphs into simple paths
- `flattenComponents` — ensures all outlines are in a single layer
- `conversionError` — controls error handling behavior

**Location:** `preview_renderer.py:79`, `gui.py:477`

---

## Issue 7: No Error Reporting When Kerning Fails Silently

**Severity:** Medium  
**Status:** ✅ Fixed  

**Symptom:** When kerning produces 0 pairs, no explanation is given to the user.

**Details:** `kerner.py:412–414`:
```python
if not metrics:
    return KerningResult()
```

This returns an empty result with no log message. The GUI logs "Generated 0 kern pairs" but offers no diagnosis (e.g., "No glyphs with contours found" or "No public.default layer detected").

**Location:** `kerner.py:412–414`, `gui.py:358–361`

**Fix applied:** `kerner.py` now emits detailed `logger.warning()` messages at every silent failure point (missing layer, empty metrics). `_on_kerning_finished` in `gui.py` surfaces these as user-visible log entries and shows a status bar message pointing users to the log panel.

---

## Issue 8: Thread Safety — Font Object Shared Across Threads

**Severity:** Medium  
**Status:** Potential risk  

**Symptom:** No crash observed yet, but the architecture is unsafe.

**Details:** `MainWindow.font` (a `ufoLib2.Font` object) is created in `open_font()` on the main thread. The `KerningWorker` opens its own copy via `ufoLib2.Font.open(self.font_path)` in the background thread. While these are separate objects, if any future code path passes `self.font` directly to the worker, concurrent access to the UFO directory (file I/O) could cause race conditions.

**Location:** `gui.py:293`, `gui.py:66–67`

---

## Issue 9: Autokerning Base Formula Causes Massive Gaps

**Severity:** Critical  
**Status:** ✅ Fixed  

**Symptom:** Kerning between specific characters (like `W`/`a`, `T`/`a`, `Y`/`s`) creates immense gaps instead of naturally tucking them closer together.

**Root Cause:** `kerner.py` computed the visual gap using `gap = right.left_sb - left.right_sb`. For glyphs with large bounding box sidebearings under their extended arms (like `W` or `T`), this calculation incorrectly produced a negative value. The engine erroneously believed the glyphs were overlapping and applied positive kerning, pushing them drastically apart. Furthermore, the kerning heuristics did not apply strong enough tucks to properly overcome the bounding-box limitations of these glyphs.

**Location:** `kerner.py`

**Fix applied:** The kerning gap calculation in `kerner.py` was fixed to correctly measure the space between bounding boxes (`real_gap = left.right_sb + right.left_sb`) and properly adjust towards a proportional `ideal_gap`. Tucking heuristic values were dramatically increased (up to -180 units) for uppercase letters (`T`, `W`, `Y`, `V`) followed by lowercase letters (like `a`, `e`, `o`, `s`) to create proper optical tucks. Additionally, an `is_latin_glyph` filter was implemented to strictly limit the automated kerning engine to Latin and common punctuation, effectively omitting Arabic and Tifinagh as requested.

---

## Summary Table

| # | Issue | Severity | Status | Root Cause File |
|---|-------|----------|--------|-----------------|
| 1 | Exported OTF has no kerning | Critical | ✅ Fixed | `gui.py` |
| 2 | Preview shows boxes | High | ✅ Fixed | `preview_renderer.py` |
| 3 | Empty kerning metrics | High | ✅ Fixed | `kerner.py` |
| 4 | No OTF/TTF import | Medium | ✅ Fixed | `gui.py` |
| 5 | Export settings confusion | Low | Open (docs only) | FontForge UI |
| 6 | Missing ufo2ft compile options | Medium | ✅ Fixed | `preview_renderer.py`, `gui.py` |
| 7 | Silent kerning failure | Medium | ✅ Fixed | `kerner.py`, `gui.py` |
| 8 | Thread safety risk | Medium | Open (no crash yet) | `gui.py` |
| 9 | Autokerning formula causes massive gaps | Critical | ✅ Fixed | `kerner.py` |
"""
gui.py - Main GUI for Font Enhancer

PyQt6-based desktop interface with:
- Font loading from UFO
- Live preview with adjustable kerning strength
- Glyph class inspection
- Export to UFO/OTF
"""

from __future__ import annotations

import os
import sys
import logging
from typing import Optional

from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QSlider,
    QTextEdit,
    QFileDialog,
    QMessageBox,
    QSplitter,
    QGroupBox,
    QCheckBox,
    QListWidget,
    QListWidgetItem,
    QComboBox,
    QStatusBar,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread
from PyQt6.QtGui import QAction, QFont, QPalette, QColor, QImage, QPixmap

import ufoLib2
from ufo2ft import compileTTF, compileOTF

from kerner import auto_kern, KerningResult, reset_kerning
from preview_renderer import PreviewFontFace, PreviewRenderer


logger = logging.getLogger(__name__)


class KerningWorker(QThread):
    """Background thread for running auto-kerning computation."""

    finished = pyqtSignal(KerningResult)
    error = pyqtSignal(str)

    def __init__(self, font_path: str, min_kern: float, max_kern: float):
        super().__init__()
        self.font_path = font_path
        self.min_kern = min_kern
        self.max_kern = max_kern

    def run(self):
        try:
            font = ufoLib2.Font.open(self.font_path)
            result = auto_kern(
                font,
                min_kern=self.min_kern,
                max_kern=self.max_kern,
            )
            # Keep font open until we return
            self._font = font
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.font: Optional[ufoLib2.Font] = None
        self.font_path: Optional[str] = None
        self.font_face: Optional[PreviewFontFace] = None
        self.renderer: Optional[PreviewRenderer] = None
        self.kerning_result: Optional[KerningResult] = None
        self.original_kerning: dict = {}

        self.min_kern = -200
        self.max_kern = 200
        self.kern_strength = 1.0
        self.show_guides = False
        self.test_strings = [
            "Hamburgefonts",
            "AVAVAWAWA",
            "ToTYorZ",
            "AVToAV",
            "Wave WAVY",
            "Ly Ly",
            "TETE TETE",
            "pepper Pepper",
            "AVAVAV",
            "To To To",
        ]
        self.current_test_index = 0

        self._init_ui()
        self._init_menubar()

    def _init_ui(self):
        self.setWindowTitle("Font Enhancer")
        self.setMinimumSize(1000, 700)

        # Detect dark/light theme
        app = QApplication.instance()
        if app:
            palette = app.palette()
        else:
            palette = QPalette()
        is_dark = palette.color(QPalette.ColorRole.Window).lightness() < 128
        self.bg_color = QColor(30, 30, 30) if is_dark else QColor(245, 245, 245)
        self.fg_color = QColor(255, 255, 255) if is_dark else QColor(20, 20, 20)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        # Left panel
        left_panel = self._create_left_panel()
        main_layout.addWidget(left_panel, 1)

        # Right panel (preview)
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(600, 300)
        self.preview_label.setStyleSheet("border: 1px solid #555;")
        main_layout.addWidget(self.preview_label, 3)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready - Open a UFO font to begin")

        # Apply Modern Dark QSS
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #1e1e1e;
                color: #e0e0e0;
                font-family: 'Inter', 'Segoe UI', sans-serif;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #333333;
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 5px;
                color: #8ab4f8;
            }
            QPushButton {
                background-color: #2d2d2d;
                border: 1px solid #444444;
                border-radius: 4px;
                padding: 6px 12px;
                color: #ffffff;
            }
            QPushButton:hover {
                background-color: #3d3d3d;
                border-color: #555555;
            }
            QPushButton:pressed {
                background-color: #505050;
            }
            QPushButton:disabled {
                background-color: #1e1e1e;
                color: #666666;
                border-color: #333333;
            }
            QPushButton#primaryBtn {
                background-color: #1a73e8;
                border: none;
                font-weight: bold;
            }
            QPushButton#primaryBtn:hover {
                background-color: #1b63c2;
            }
            QPushButton#primaryBtn:disabled {
                background-color: #1a3a5c;
                color: #888888;
            }
            QSlider::groove:horizontal {
                border: 1px solid #333;
                height: 6px;
                background: #2a2a2a;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #8ab4f8;
                border: 1px solid #8ab4f8;
                width: 14px;
                margin: -4px 0;
                border-radius: 7px;
            }
            QTableWidget, QListWidget, QTextEdit {
                background-color: #252525;
                border: 1px solid #333333;
                border-radius: 4px;
                gridline-color: #333333;
            }
            QHeaderView::section {
                background-color: #2d2d2d;
                padding: 4px;
                border: 1px solid #333333;
                font-weight: bold;
            }
            QComboBox {
                background-color: #2d2d2d;
                border: 1px solid #444444;
                border-radius: 4px;
                padding: 4px;
            }
            QComboBox::drop-down {
                border: none;
            }
        """)

    def _create_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        # File controls
        file_group = QGroupBox("Font File")
        file_layout = QVBoxLayout(file_group)

        self.open_btn = QPushButton("Open UFO Font...")
        self.open_btn.clicked.connect(self.open_font)
        file_layout.addWidget(self.open_btn)

        self.font_name_label = QLabel("No font loaded")
        self.font_name_label.setStyleSheet("font-weight: bold;")
        file_layout.addWidget(self.font_name_label)

        layout.addWidget(file_group)

        # Kerning controls
        kern_group = QGroupBox("Auto-Kerning")
        kern_layout = QVBoxLayout(kern_group)

        self.auto_kern_btn = QPushButton("Run Auto-Kern")
        self.auto_kern_btn.setObjectName("primaryBtn")
        self.auto_kern_btn.clicked.connect(self.run_auto_kern)
        self.auto_kern_btn.setEnabled(False)
        kern_layout.addWidget(self.auto_kern_btn)

        kern_layout.addWidget(QLabel("Kerning Strength"))
        self.strength_slider = QSlider(Qt.Orientation.Horizontal)
        self.strength_slider.setRange(-100, 100)
        self.strength_slider.setValue(100)
        self.strength_slider.valueChanged.connect(self.on_strength_changed)
        kern_layout.addWidget(self.strength_slider)

        self.strength_label = QLabel("1.0")
        self.strength_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        kern_layout.addWidget(self.strength_label)

        self.reset_btn = QPushButton("Reset to Original")
        self.reset_btn.clicked.connect(self.reset_kerning)
        self.reset_btn.setEnabled(False)
        kern_layout.addWidget(self.reset_btn)

        layout.addWidget(kern_group)

        # Preview controls
        preview_group = QGroupBox("Preview")
        preview_layout = QVBoxLayout(preview_group)

        self.test_string_combo = QComboBox()
        self.test_string_combo.addItems(self.test_strings)
        self.test_string_combo.setEditable(True)
        self.test_string_combo.currentTextChanged.connect(self.update_preview)
        preview_layout.addWidget(QLabel("Test String:"))
        preview_layout.addWidget(self.test_string_combo)

        self.guides_check = QCheckBox("Show Guides")
        self.guides_check.toggled.connect(self.on_guides_toggled)
        preview_layout.addWidget(self.guides_check)

        self.direction_combo = QComboBox()
        self.direction_combo.addItems(["LTR (Latin)", "RTL (Arabic/Tifinagh)"])
        self.direction_combo.currentIndexChanged.connect(self.update_preview)
        preview_layout.addWidget(QLabel("Direction:"))
        preview_layout.addWidget(self.direction_combo)

        preview_layout.addWidget(QLabel("Font Size"))
        self.font_size_slider = QSlider(Qt.Orientation.Horizontal)
        self.font_size_slider.setRange(24, 200)
        self.font_size_slider.setValue(72)
        self.font_size_slider.valueChanged.connect(self.update_preview)
        preview_layout.addWidget(self.font_size_slider)

        layout.addWidget(preview_group)

        # Kerning Pairs Table
        pairs_group = QGroupBox("Kerning Pairs")
        pairs_layout = QVBoxLayout(pairs_group)

        self.pairs_table = QTableWidget()
        self.pairs_table.setColumnCount(3)
        self.pairs_table.setHorizontalHeaderLabels(["Left", "Right", "Value"])
        self.pairs_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.pairs_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.pairs_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.pairs_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.pairs_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.pairs_table.setMaximumHeight(200)
        pairs_layout.addWidget(self.pairs_table)

        layout.addWidget(pairs_group)

        # Export controls
        export_group = QGroupBox("Export")
        export_layout = QVBoxLayout(export_group)

        self.export_ufo_btn = QPushButton("Export UFO (re-import)")
        self.export_ufo_btn.clicked.connect(self.export_ufo)
        self.export_ufo_btn.setEnabled(False)
        export_layout.addWidget(self.export_ufo_btn)

        self.export_otf_btn = QPushButton("Export OTF (final)")
        self.export_otf_btn.clicked.connect(self.export_otf)
        self.export_otf_btn.setEnabled(False)
        export_layout.addWidget(self.export_otf_btn)

        layout.addWidget(export_group)

        # Log
        self.log_text = QTextEdit()
        self.log_text.setMaximumHeight(100)
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("font-family: monospace; font-size: 9pt;")
        layout.addWidget(QLabel("Log:"))
        layout.addWidget(self.log_text)

        layout.addStretch()
        return panel

    def _init_menubar(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("File")

        open_action = QAction("Open UFO...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.open_font)
        file_menu.addAction(open_action)

        open_compiled_action = QAction("Open OTF/TTF (preview-only)...", self)
        open_compiled_action.setShortcut("Ctrl+Shift+O")
        open_compiled_action.triggered.connect(self.open_compiled_font)
        file_menu.addAction(open_compiled_action)

        file_menu.addSeparator()

        exit_action = QAction("Exit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        help_menu = menubar.addMenu("Help")

        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def log(self, message: str):
        self.log_text.append(message)
        logger.info(message)

    def load_font_from_path(self, path: str):
        """Load font from a given path (for CLI usage).

        Supports both UFO directories and compiled .otf/.ttf files.
        Compiled fonts run in preview-only mode (no kerning engine).
        """
        is_compiled = os.path.isfile(path) and path.lower().endswith((".otf", ".ttf"))

        if not is_compiled and not os.path.isdir(path):
            self.log(f"Error: Path is not a UFO directory or a .otf/.ttf file: {path}")
            return

        if is_compiled:
            try:
                self.font_path = path
                self.font = None
                self.font_face = PreviewFontFace.from_file(path)
                self.renderer = PreviewRenderer(self.font_face)
                self.font_name_label.setText(os.path.basename(path) + " (preview-only)")
                self.log(f"Loaded compiled font (preview-only): {path}")
                self.log("Note: Auto-kerning and UFO export are not available for compiled fonts.")
                self.status_bar.showMessage(f"Preview-only: {os.path.basename(path)}")
                self.auto_kern_btn.setEnabled(False)
                self.export_ufo_btn.setEnabled(False)
                self.export_otf_btn.setEnabled(False)
                self.update_preview()
            except Exception as e:
                self.log(f"Error loading compiled font: {e}")
            return

        try:
            self.font_path = path
            self.font = ufoLib2.Font.open(path)
            name = self.font.info.familyName or os.path.basename(path)
            self.font_name_label.setText(name)

            self.log(f"Compiling UFO for preview: {path}")
            self.font_face = PreviewFontFace.from_ufo(path)
            self.renderer = PreviewRenderer(self.font_face)

            self.log(f"Loaded font: {path}")
            self.status_bar.showMessage(f"Loaded: {os.path.basename(path)}")

            self.auto_kern_btn.setEnabled(True)
            self.export_ufo_btn.setEnabled(True)
            self.export_otf_btn.setEnabled(True)

            self.update_preview()
            self.log("Font loaded successfully. Click 'Run Auto-Kern' to begin.")

        except Exception as e:
            self.log(f"Error loading font: {e}")
            QMessageBox.critical(self, "Error", f"Failed to load font:\n{e}")

    def open_font(self):
        path = QFileDialog.getExistingDirectory(
            self, "Open UFO Font Directory", "", QFileDialog.Option.ShowDirsOnly
        )
        if not path:
            return

        try:
            self.font_path = path
            self.font = ufoLib2.Font.open(path)
            name = self.font.info.familyName or os.path.basename(path)
            self.font_name_label.setText(name)

            self.log(f"Compiling UFO for preview: {path}")
            self.font_face = PreviewFontFace.from_ufo(path)
            self.renderer = PreviewRenderer(self.font_face)

            self.log(f"Loaded UFO font: {path}")
            self.status_bar.showMessage(f"Loaded: {os.path.basename(path)}")

            self.auto_kern_btn.setEnabled(True)
            self.export_ufo_btn.setEnabled(True)
            self.export_otf_btn.setEnabled(True)

            self.update_preview()
            self.log("Font loaded successfully. Click 'Run Auto-Kern' to begin.")

        except Exception as e:
            self.log(f"Error loading font: {e}")
            QMessageBox.critical(self, "Error", f"Failed to load font:\n{e}")

    def open_compiled_font(self):
        """Load a compiled .otf or .ttf file (preview-only, no kerning engine)."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Compiled Font",
            "",
            "Font Files (*.otf *.ttf);;OpenType (*.otf);;TrueType (*.ttf)",
        )
        if not path:
            return

        try:
            self.font_path = path
            self.font = None  # No UFO model available for compiled fonts

            self.font_face = PreviewFontFace.from_file(path)
            self.renderer = PreviewRenderer(self.font_face)

            self.font_name_label.setText(os.path.basename(path) + " (preview-only)")
            self.log(f"Loaded compiled font: {path}")
            self.log("Note: Auto-kerning and UFO export are not available for compiled fonts.")
            self.status_bar.showMessage(f"Preview-only: {os.path.basename(path)}")

            # Kerning engine requires UFO; disable those controls
            self.auto_kern_btn.setEnabled(False)
            self.export_ufo_btn.setEnabled(False)
            self.export_otf_btn.setEnabled(False)

            self.update_preview()

        except Exception as e:
            self.log(f"Error loading compiled font: {e}")
            QMessageBox.critical(self, "Error", f"Failed to load font:\n{e}")

    def run_auto_kern(self):
        if not self.font or not self.font_path:
            return

        self.log("Running auto-kerning...")
        self.auto_kern_btn.setEnabled(False)
        self.status_bar.showMessage("Computing kerning pairs...")

        self.worker = KerningWorker(self.font_path, self.min_kern, self.max_kern)
        self.worker.finished.connect(self._on_kerning_finished)
        self.worker.error.connect(self._on_kerning_error)
        self.worker.start()

    def _on_kerning_finished(self, result: KerningResult):
        self.kerning_result = result

        if not result.glyph_pairs:
            self.log(
                "WARNING: Generated 0 kern pairs. "
                "Check the log above for details on why metrics were empty. "
                "Possible causes: no glyphs with contours, missing 'public.default' layer, "
                "or only component-only glyphs in this font."
            )
            self.auto_kern_btn.setEnabled(True)
            self.status_bar.showMessage("Auto-kerning produced 0 pairs — see log")
            return

        # --- Issue 1 fix: write computed kerning back to self.font ---
        # Save original kerning before overwriting so Reset works correctly.
        if self.font is not None:
            self.original_kerning = dict(self.font.kerning)
            # Apply computed glyph pairs to the in-memory font object so that
            # export_ufo() and export_otf() always see up-to-date kerning.
            self.font.kerning.clear()
            for (left, right), value in result.glyph_pairs.items():
                adjusted = round(value * self.kern_strength, 1)
                if abs(adjusted) >= 0.5:
                    self.font.kerning[(left, right)] = adjusted

        self.log(f"Generated {len(result.glyph_pairs)} kern pairs")
        self.log(f"Left classes: {len(result.left_classes)}")
        self.log(f"Right classes: {len(result.right_classes)}")

        # Update Pairs Table
        self.pairs_table.setRowCount(0)
        if result.class_pairs:
            # Sort by absolute value descending
            sorted_pairs = sorted(result.class_pairs, key=lambda p: abs(p.value), reverse=True)
            for cp in sorted_pairs:
                row = self.pairs_table.rowCount()
                self.pairs_table.insertRow(row)
                self.pairs_table.setItem(row, 0, QTableWidgetItem(cp.left_class))
                self.pairs_table.setItem(row, 1, QTableWidgetItem(cp.right_class))
                
                val_item = QTableWidgetItem(str(round(cp.value, 1)))
                val_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.pairs_table.setItem(row, 2, val_item)

        if self.renderer:
            self.renderer.kern_pairs = result.glyph_pairs

        self.reset_btn.setEnabled(True)
        self.auto_kern_btn.setEnabled(True)
        self.update_preview()
        self.status_bar.showMessage(f"Auto-kerning complete — {len(result.glyph_pairs)} pairs")

    def _on_kerning_error(self, error: str):
        self.log(f"Kerning error: {error}")
        self.auto_kern_btn.setEnabled(True)
        self.status_bar.showMessage("Kerning failed")

    def on_strength_changed(self, value: int):
        self.kern_strength = value / 100.0
        self.strength_label.setText(f"{self.kern_strength:.1f}")
        if self.renderer:
            self.renderer.kern_strength = self.kern_strength
        # Keep self.font.kerning in sync with the new strength so exports
        # always reflect the current slider position.
        if self.font is not None and self.kerning_result and self.kerning_result.glyph_pairs:
            self.font.kerning.clear()
            for (left, right), value_raw in self.kerning_result.glyph_pairs.items():
                adjusted = round(value_raw * self.kern_strength, 1)
                if abs(adjusted) >= 0.5:
                    self.font.kerning[(left, right)] = adjusted
        self.update_preview()

    def on_guides_toggled(self, checked: bool):
        self.show_guides = checked
        self.update_preview()

    def reset_kerning(self):
        if not self.font or not self.original_kerning:
            return

        reset_kerning(self.font)
        for k, v in self.original_kerning.items():
            self.font.kerning[k] = v

        self.log("Kerning reset to original")
        self.update_preview()

    def update_preview(self):
        if not self.renderer:
            return

        test_text = self.test_string_combo.currentText()
        if not test_text:
            return

        direction = "rtl" if self.direction_combo.currentIndex() == 1 else "ltr"
        self.renderer.direction = direction

        font_size = self.font_size_slider.value()
        self.renderer.font_size = float(font_size)

        try:
            image = self.renderer.render(
                test_text,
                width=self.preview_label.width(),
                height=self.preview_label.height(),
                show_guides=self.show_guides,
                fg_color=self.fg_color,
                bg_color=self.bg_color,
            )
            scaled = image.scaled(
                self.preview_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.preview_label.setPixmap(QPixmap.fromImage(scaled))
        except Exception as e:
            self.log(f"Preview error: {e}")

    def export_ufo(self):
        if not self.font or not self.font_path:
            return

        out_dir = QFileDialog.getExistingDirectory(
            self, "Export as UFO", self.font_path + "_kerned"
        )
        if not out_dir:
            return

        try:
            self.font.save(out_dir)
            self.log(f"Exported UFO to: {out_dir}")
            QMessageBox.information(
                self,
                "Export Complete",
                f"UFO exported to:\n{out_dir}\n\n"
                "You can re-import this UFO into FontForge.",
            )
        except Exception as e:
            self.log(f"Export error: {e}")
            QMessageBox.critical(self, "Export Error", str(e))

    def export_otf(self):
        if not self.font or not self.font_path:
            return

        out_file, _ = QFileDialog.getSaveFileName(
            self, "Export as OTF", self.font_path + ".otf", "OpenType Font (*.otf)"
        )
        if not out_file:
            return

        try:
            # --- Issue 1 fix: re-open from disk then apply computed kerning ---
            # self.font.kerning is kept in sync by _on_kerning_finished and
            # on_strength_changed, so we copy from there instead of re-reading
            # an empty disk file.
            font = ufoLib2.Font.open(self.font_path)

            # Propagate the in-memory kerning (written by _on_kerning_finished)
            kerning_source = self.font.kerning
            if not kerning_source and self.kerning_result:
                # Defensive fallback: re-apply from KerningResult directly
                for (left, right), val in self.kerning_result.glyph_pairs.items():
                    adjusted = round(val * self.kern_strength, 1)
                    if abs(adjusted) >= 0.5:
                        font.kerning[(left, right)] = adjusted
            else:
                for k, v in kerning_source.items():
                    font.kerning[k] = v

            self.log(
                f"Compiling OTF with {len(font.kerning)} kerning entries..."
            )

            # --- Issue 6 fix: pass compile options for better FontForge compat ---
            otf = compileOTF(
                font,
                removeOverlaps=True,
            )
            otf.save(out_file)

            self.log(f"Exported OTF to: {out_file}")
            QMessageBox.information(
                self, "Export Complete", f"OTF exported to:\n{out_file}"
            )
        except Exception as e:
            self.log(f"Export error: {e}")
            QMessageBox.critical(self, "Export Error", str(e))

    def show_about(self):
        QMessageBox.about(
            self,
            "About Font Enhancer",
            "<h3>Font Enhancer</h3>"
            "<p>Open-source font kerning automation tool.</p>"
            "<p>Integrates with FontForge via UFO interchange format.</p>"
            "<p>Uses fonttools, ufoLib2, harfbuzz, and freetype-py.</p>",
        )

    def closeEvent(self, event):
        if self.font_face:
            self.font_face.cleanup()
        event.accept()


def main(args=None):
    app = QApplication(sys.argv)
    app.setApplicationName("Font Enhancer")

    window = MainWindow()
    window.show()

    # Handle command line arguments
    if args and args.font:
        logger.info(f"Auto-loading font from: {args.font}")
        # Load font programmatically
        QTimer.singleShot(500, lambda: window.load_font_from_path(args.font))

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

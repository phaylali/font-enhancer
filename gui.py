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

        # Glyph classes (read-only for now)
        classes_group = QGroupBox("Glyph Classes")
        classes_layout = QVBoxLayout(classes_group)

        self.classes_list = QListWidget()
        self.classes_list.setMaximumHeight(150)
        classes_layout.addWidget(self.classes_list)

        layout.addWidget(classes_group)

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
        """Load font from a given path (for CLI usage)."""
        if not os.path.isdir(path):
            self.log(f"Error: Not a valid directory: {path}")
            return

        try:
            self.font_path = path
            self.font = ufoLib2.Font.open(path)
            self.font_name_label.setText(self.font.info.familyName or "Unnamed")

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
            self.font_name_label.setText(self.font.info.familyName or "Unnamed")

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
        self.original_kerning = dict(self.font.kerning)

        self.log(f"Generated {len(result.glyph_pairs)} kern pairs")
        self.log(f"Left classes: {len(result.left_classes)}")
        self.log(f"Right classes: {len(result.right_classes)}")

        # Update classes list
        self.classes_list.clear()
        for cls_name, members in result.left_classes.items():
            item = f"{cls_name}: {', '.join(members[:5])}"
            if len(members) > 5:
                item += f"... (+{len(members) - 5})"
            self.classes_list.addItem(item)

        if self.renderer:
            self.renderer.kern_pairs = result.glyph_pairs

        self.reset_btn.setEnabled(True)
        self.auto_kern_btn.setEnabled(True)
        self.update_preview()
        self.status_bar.showMessage("Auto-kerning complete")

    def _on_kerning_error(self, error: str):
        self.log(f"Kerning error: {error}")
        self.auto_kern_btn.setEnabled(True)
        self.status_bar.showMessage("Kerning failed")

    def on_strength_changed(self, value: int):
        self.kern_strength = value / 100.0
        self.strength_label.setText(f"{self.kern_strength:.1f}")
        if self.renderer:
            self.renderer.kern_strength = self.kern_strength
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
            font = ufoLib2.Font.open(self.font_path)
            if self.font.kerning:
                for k, v in self.font.kerning.items():
                    font.kerning[k] = v

            otf = compileOTF(font)
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

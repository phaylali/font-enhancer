"""
preview_renderer.py - Text shaping and rendering for Font Enhancer

Uses freetype-py for font rasterization. Text shaping is simplified for
basic rendering - complex RTL/Arabic shaping would require additional setup.

Note on Arabic / Tifinagh / complex scripts:
    The OpenType `kern` table only handles basic pair spacing. Complex
    RTL and contextual shaping is not fully supported in this version.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import freetype
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPainter, QColor, QPen


@dataclass
class GlyphInfo:
    """Basic glyph information for rendering."""

    glyph_id: int
    glyph_name: str
    advance_width: float


# ---------------------------------------------------------------------------
# Font face loading
# ---------------------------------------------------------------------------


class PreviewFontFace:
    """
    Wraps a freetype face for rendering.

    Can load from a compiled font file (.otf/.ttf) or from a UFO via
    on-the-fly compilation using fonttools.
    """

    def __init__(self, ft_face: freetype.Face):
        self.ft_face = ft_face
        self._glyph_name_map: dict[int, str] = {}
        self._build_glyph_map()

    def _build_glyph_map(self):
        """Build mapping from glyph ID to glyph name."""
        try:
            for i, name in enumerate(self.ft_face.get_glyph_order()):
                self._glyph_name_map[i + 1] = name
        except Exception:
            pass

    @property
    def units_per_em(self) -> int:
        return self.ft_face.units_per_EM

    @classmethod
    def from_file(cls, path: str) -> "PreviewFontFace":
        """Load a compiled font file (.otf or .ttf)."""
        ft_face = freetype.Face(path)
        return cls(ft_face)

    @classmethod
    def from_ufo(cls, ufo_path: str) -> "PreviewFontFace":
        """
        Load a UFO directory by compiling it to a temporary TTF using
        fonttools, then loading the result.
        """
        import tempfile
        from ufo2ft import compileTTF
        from ufoLib2 import Font

        ufo = Font.open(ufo_path)
        ttf = compileTTF(ufo)

        tmp = tempfile.NamedTemporaryFile(
            suffix=".ttf", delete=False, prefix="fontenhancer_"
        )
        tmp.close()
        ttf.save(tmp.name)

        face = cls.from_file(tmp.name)
        face._tmp_path = tmp.name
        return face

    def cleanup(self):
        """Remove temporary compiled font file if one was created."""
        tmp = getattr(self, "_tmp_path", None)
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)

    def get_glyph_id(self, name: str) -> int:
        """Get glyph ID by name."""
        try:
            return self.ft_face.get_glyph_index(name)
        except Exception:
            return 0

    def get_glyph_name(self, gid: int) -> str:
        """Get glyph name by ID."""
        return self._glyph_name_map.get(gid, f"glyph{gid}")


# ---------------------------------------------------------------------------
# Simple text rendering (no harfbuzz shaping)
# ---------------------------------------------------------------------------


def render_simple_text(
    font_face: PreviewFontFace,
    text: str,
    font_size: float = 72.0,
    fg_color: QColor = QColor(255, 255, 255),
    bg_color: QColor = QColor(30, 30, 30),
) -> QImage:
    """
    Render text using freetype directly (basic rendering without shaping).
    """
    ft_face = font_face.ft_face

    # Set font size
    ft_face.set_char_size(0, int(font_size * 64), 72, 72)

    # Calculate dimensions
    total_width = 0
    max_height = 0
    glyphs_data = []

    for char in text:
        glyph_index = ft_face.get_char_index(ord(char))
        ft_face.load_glyph(glyph_index)
        glyph = ft_face.glyph
        metrics = glyph.metrics

        advance = metrics.horiAdvance / 64.0
        total_width += advance

        bitmap = glyph.bitmap
        rows = bitmap.rows
        width = bitmap.width
        if rows > max_height:
            max_height = rows

        glyphs_data.append(
            {
                "index": glyph_index,
                "advance": advance,
                "bitmap": bitmap,
                "left": glyph.bitmap_left,
                "top": glyph.bitmap_top,
            }
        )

    # Create image
    padding = 20
    width = int(total_width) + padding * 2
    height = max_height + padding * 2

    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(bg_color)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Draw each glyph
    x = padding
    baseline = height - padding

    for gd in glyphs_data:
        ft_face.load_glyph(gd["index"])
        bitmap = gd["bitmap"]

        if bitmap.buffer and bitmap.width > 0 and bitmap.rows > 0:
            # Convert freetype buffer to bytes
            img_data = bytes(bitmap.buffer)
            glyph_img = QImage(
                img_data,
                bitmap.width,
                bitmap.rows,
                bitmap.pitch,
                QImage.Format.Format_Grayscale8,
            )

            tinted = QImage(glyph_img.size(), QImage.Format.Format_ARGB32)
            tinted.fill(Qt.GlobalColor.transparent)
            tp = QPainter(tinted)
            tp.drawImage(0, 0, glyph_img)
            tp.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            tp.fillRect(tinted.rect(), fg_color)
            tp.end()

            px = int(x + gd["left"])
            py = int(baseline - gd["top"])
            painter.drawImage(px, py, tinted)

        x += int(gd["advance"])

    painter.end()
    return image


# ---------------------------------------------------------------------------
# High-level preview API
# ---------------------------------------------------------------------------


class PreviewRenderer:
    """
    High-level renderer for text preview.
    """

    def __init__(self, font_face: PreviewFontFace):
        self.font_face = font_face
        self._kern_pairs: dict[tuple[str, str], float] = {}
        self._kern_strength = 1.0
        self._font_size = 72.0

    @property
    def kern_pairs(self) -> dict[tuple[str, str], float]:
        return self._kern_pairs

    @kern_pairs.setter
    def kern_pairs(self, value: dict[tuple[str, str], float]) -> None:
        self._kern_pairs = value

    @property
    def kern_strength(self) -> float:
        return self._kern_strength

    @kern_strength.setter
    def kern_strength(self, value: float) -> None:
        self._kern_strength = max(-1.0, min(1.0, value))

    @property
    def font_size(self) -> float:
        return self._font_size

    @font_size.setter
    def font_size(self, value: float) -> None:
        self._font_size = max(8.0, min(500.0, value))

    def render(
        self,
        text: str,
        width: int = 800,
        height: int = 200,
        show_guides: bool = False,
        fg_color: QColor = QColor(255, 255, 255),
        bg_color: QColor = QColor(30, 30, 30),
    ) -> QImage:
        """Render text to an image."""
        # Note: kern_pairs and show_guides not yet implemented in simple renderer
        return render_simple_text(
            self.font_face,
            text,
            font_size=self._font_size,
            fg_color=fg_color,
            bg_color=bg_color,
        )

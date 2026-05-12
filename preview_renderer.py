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

import uharfbuzz as hb
import freetype
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPainter, QColor, QPen, QBrush


@dataclass
class GlyphInfo:
    """Basic glyph information for rendering."""

    glyph_id: int
    glyph_name: str
    advance_width: float


# ---------------------------------------------------------------------------
# Latin character detection
# ---------------------------------------------------------------------------


def is_latin_character(char: str) -> bool:
    """
    Return True if *char* belongs to Basic Latin (U+0000–U+007F) or
    Latin-1 Supplement (U+0080–U+00FF).

    These are the only ranges for which the 6-point kerning anchor overlay
    is drawn, matching the is_latin_glyph() filter in kerner.py.
    """
    if not char:
        return False
    return ord(char[0]) <= 0x00FF


def draw_kerning_anchor_points(
    painter: QPainter,
    left_x: int,
    right_x: int,
    top_y: int,
    bottom_y: int,
    color: QColor = QColor(255, 80, 80, 200),
    radius: int = 3,
) -> None:
    """
    Draw the 6 kerning reference anchor dots for one glyph.

    Dots are placed at the **ink bounding-box edges** (not advance-width
    edges) so designers can judge the actual optical gap between glyphs:

      Left edge  → top-left,   center-left,  bottom-left
      Right edge → top-right,  center-right, bottom-right

    Args:
        painter:  Active QPainter on the preview image.
        left_x:   X pixel of the left ink edge.
        right_x:  X pixel of the right ink edge.
        top_y:    Y pixel of the topmost ink row.
        bottom_y: Y pixel of the bottommost ink row.
        color:    Dot fill color (default: soft red, semi-transparent).
        radius:   Dot radius in pixels.
    """
    center_y = (top_y + bottom_y) // 2
    anchor_points = [
        (left_x,  top_y),
        (left_x,  center_y),
        (left_x,  bottom_y),
        (right_x, top_y),
        (right_x, center_y),
        (right_x, bottom_y),
    ]
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(color))
    for px, py in anchor_points:
        painter.drawEllipse(px - radius, py - radius, radius * 2, radius * 2)
    painter.restore()


# ---------------------------------------------------------------------------
# Font face loading
# ---------------------------------------------------------------------------


class PreviewFontFace:
    """
    Wraps a freetype face and uharfbuzz font for text shaping and rendering.
    """

    def __init__(self, ft_face: freetype.Face, hb_font: hb.Font, hb_face: hb.Face):
        self.ft_face = ft_face
        self.hb_font = hb_font
        self.hb_face = hb_face
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
        with open(path, "rb") as f:
            fontdata = f.read()
        hb_face = hb.Face(fontdata)
        hb_font = hb.Font(hb_face)
        return cls(ft_face, hb_font, hb_face)

    @classmethod
    def from_ufo(cls, ufo_path: str) -> "PreviewFontFace":
        """
        Load a UFO directory by compiling it to a temporary TTF using
        fonttools, then loading the result.

        Passes removeOverlaps and decomposeComponents to handle common
        FontForge UFO export edge cases (overlapping paths, composite glyphs)
        that would otherwise produce empty/box glyphs in the preview.
        """
        import tempfile
        from ufo2ft import compileTTF
        from ufoLib2 import Font

        ufo = Font.open(ufo_path)
        ttf = compileTTF(
            ufo,
            removeOverlaps=True,
        )

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


def render_shaped_text(
    font_face: PreviewFontFace,
    text: str,
    font_size: float = 72.0,
    direction: str = "ltr",
    fg_color: QColor = QColor(255, 255, 255),
    bg_color: QColor = QColor(30, 30, 30),
    show_kerning_points: bool = False,
) -> QImage:
    """
    Render text using uharfbuzz for shaping and freetype for rasterization.
    This properly handles RTL, cursive connections, and complex ligatures.
    """
    ft_face = font_face.ft_face
    hb_font = font_face.hb_font

    # Set font sizes
    # uharfbuzz operates in upem or scaled values. We set scaling to match font_size.
    # We use 64 * font_size for freetype to match 72 DPI (1 pt = 1 px).
    pixel_size = int(font_size)
    hb_font.scale = (pixel_size * 64, pixel_size * 64)
    
    ft_face.set_char_size(0, pixel_size * 64, 72, 72)

    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    
    # Override direction if specified
    if direction == "rtl":
        buf.direction = "rtl"
    elif direction == "ltr":
        buf.direction = "ltr"

    hb.shape(hb_font, buf)

    infos = buf.glyph_infos
    positions = buf.glyph_positions

    glyphs_data = []
    current_x = 0
    current_y = 0

    min_x = 0
    max_x = 0
    max_height = pixel_size

    for info, pos in zip(infos, positions):
        gid = info.codepoint
        ft_face.load_glyph(gid)
        glyph = ft_face.glyph
        bitmap = glyph.bitmap

        # pos values are scaled because of hb_font.scale
        x_offset = pos.x_offset / 64.0
        y_offset = pos.y_offset / 64.0
        x_advance = pos.x_advance / 64.0
        y_advance = pos.y_advance / 64.0

        gx = current_x + x_offset
        gy = current_y + y_offset

        if bitmap.rows > max_height:
            max_height = bitmap.rows

        # Resolve the source character for this glyph via the cluster index.
        # info.cluster is the byte offset into *text* for the first code-point
        # that produced this glyph.  For BMP text this equals the char index.
        cluster_idx = getattr(info, "cluster", 0)
        try:
            source_char = text[cluster_idx]
        except (IndexError, TypeError):
            source_char = ""

        glyphs_data.append({
            "index": gid,
            "x": gx,
            "y": gy,
            "advance": x_advance,
            "bitmap": bitmap,
            "left": glyph.bitmap_left,
            "top": glyph.bitmap_top,
            "char": source_char,
        })

        current_x += x_advance
        current_y += y_advance
        
        if current_x < min_x:
            min_x = current_x
        if current_x > max_x:
            max_x = current_x

    padding = int(font_size * 0.5)
    
    # For RTL, current_x ends up negative, so total width is max_x - min_x
    total_width = max_x - min_x
    if total_width == 0 and glyphs_data:
        # Fallback for single glyph or 0 advance
        total_width = font_size

    width = int(total_width) + padding * 2
    height = int(max_height) + padding * 2

    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(bg_color)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Calculate baseline and starting x
    baseline = height - padding
    
    # If RTL, the drawing progresses negatively, so we start at the right side of the box
    if current_x < 0:
        start_x = width - padding
    else:
        start_x = padding

    # Dot color: soft red, semi-transparent — visible on both dark and light bg
    anchor_color = QColor(255, 80, 80, 210)
    # Scale dot radius with font size so it stays proportionate
    dot_radius = max(2, int(font_size * 0.04))

    for gd in glyphs_data:
        ft_face.load_glyph(gd["index"])
        bitmap = gd["bitmap"]

        if bitmap.buffer and bitmap.width > 0 and bitmap.rows > 0:
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

            px = int(start_x + gd["x"] + gd["left"])
            py = int(baseline - gd["y"] - gd["top"])
            painter.drawImage(px, py, tinted)

            # --- 6-point kerning anchor overlay ---
            # Drawn only when guides are enabled AND the glyph maps to a
            # Latin / Latin-1 Supplement character (U+0000–U+00FF).
            if show_kerning_points and is_latin_character(gd.get("char", "")):
                left_x  = px
                right_x = px + bitmap.width
                top_y    = py
                bottom_y = py + bitmap.rows
                draw_kerning_anchor_points(
                    painter,
                    left_x, right_x,
                    top_y, bottom_y,
                    color=anchor_color,
                    radius=dot_radius,
                )

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
        self.direction = "ltr"

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
        """
        Render text to an image.

        When *show_guides* is True, each Latin/Latin-Supplement character
        receives 6 kerning reference dots (top/center/bottom on both the
        left and right ink edges) to assist in evaluating pair accuracy.

        Note on live kerning visualisation:
            Harfbuzz shaping uses the compiled font's built-in kern table.
            The auto-kern values are applied to `ufoLib2.Font` and only
            become visible in the preview after an OTF re-export and reload.
            The anchor dots are always drawn from the current rasterised
            ink bounds regardless of kern state.
        """
        return render_shaped_text(
            self.font_face,
            text,
            font_size=self._font_size,
            direction=getattr(self, "direction", "ltr"),
            fg_color=fg_color,
            bg_color=bg_color,
            show_kerning_points=show_guides,
        )

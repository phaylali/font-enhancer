"""
kerner.py - Auto-kerning engine for Font Enhancer

Generates glyph classes from metric similarity, calculates class-based kerning
pairs using weighted heuristics (sidebearing overlap, advance width delta,
optical bounding box), and applies adjustments capped to user-defined ranges.

All algorithms are open-source and require no external APIs.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Optional

from ufoLib2 import Font
from defcon import Glyph


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Glyph classification helpers
# ---------------------------------------------------------------------------

# Manual glyph class templates for common Latin shapes.
# These serve as starting points; the auto-classifier refines them using
# actual metric data from the loaded UFO.
LATIN_LEFT_CLASSES: dict[str, list[str]] = {
    "O_left": ["O", "C", "Q", "G", "D", "c", "e", "o", "d", "q", "g"],
    "V_left": ["V", "W", "Y", "v", "w", "y", "K", "X", "x", "k"],
    "H_left": [
        "H",
        "I",
        "B",
        "E",
        "F",
        "L",
        "T",
        "J",
        "h",
        "b",
        "l",
        "f",
        "i",
        "j",
        "t",
        "r",
        "n",
        "m",
        "p",
        "u",
    ],
    "A_left": ["A", "N", "M", "Z", "S", "a", "n", "m", "z", "s"],
    "R_left": ["R", "P", "a"],
    "slash_left": ["slash", "backslash", "f", "/"],
}

LATIN_RIGHT_CLASSES: dict[str, list[str]] = {
    "O_right": ["O", "C", "Q", "G", "D", "c", "e", "o", "b", "p", "d", "q"],
    "V_right": ["V", "W", "Y", "v", "w", "y", "A", "X", "x", "K", "k"],
    "H_right": [
        "H",
        "I",
        "B",
        "E",
        "F",
        "L",
        "T",
        "J",
        "h",
        "b",
        "l",
        "f",
        "i",
        "j",
        "t",
        "r",
        "n",
        "m",
        "p",
        "u",
    ],
    "A_right": ["A", "N", "M", "Z", "S", "a", "n", "m", "z", "s"],
    "R_right": ["R", "P"],
    "slash_right": ["slash", "backslash", "f", "/"],
}


@dataclass
class GlyphMetrics:
    """Cached geometric data for a single glyph."""

    name: str
    left_sb: float = 0.0
    right_sb: float = 0.0
    advance_width: float = 0.0
    bbox: tuple[float, float, float, float] = (0, 0, 0, 0)
    contour_area: float = 0.0
    has_contours: bool = False


@dataclass
class KernPair:
    """A single kerning pair with its computed adjustment."""

    left_glyph: str
    right_glyph: str
    value: float  # in font units (negative = tighter)


@dataclass
class ClassKernPair:
    """Class-to-class kerning entry."""

    left_class: str
    right_class: str
    value: float


# ---------------------------------------------------------------------------
# Metric extraction
# ---------------------------------------------------------------------------


def extract_metrics(glyph: Glyph) -> GlyphMetrics:
    """Extract sidebearings, advance width, and bounding box from a glyph."""
    m = GlyphMetrics(name=glyph.name)
    m.advance_width = glyph.width
    m.has_contours = len(glyph) > 0

    if m.has_contours:
        bbox = glyph.getControlBounds()
        if bbox:
            m.bbox = bbox
            m.left_sb = bbox[0]
            m.right_sb = glyph.width - bbox[2]
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            m.contour_area = w * h
        else:
            m.left_sb = 0
            m.right_sb = glyph.width
    else:
        m.left_sb = 0
        m.right_sb = glyph.width

    return m


# ---------------------------------------------------------------------------
# Auto-classification
# ---------------------------------------------------------------------------


def _metric_distance(a: GlyphMetrics, b: GlyphMetrics) -> float:
    """Weighted Euclidean distance between two glyph metric profiles."""
    # Normalise by average advance to make distance scale-invariant
    avg_adv = max((a.advance_width + b.advance_width) / 2, 1.0)

    d_left = (a.left_sb - b.left_sb) / avg_adv
    d_right = (a.right_sb - b.right_sb) / avg_adv
    d_adv = (a.advance_width - b.advance_width) / avg_adv
    d_area = (a.contour_area - b.contour_area) / (avg_adv**2 + 1)

    # Weights tuned empirically for Latin glyphs
    return math.sqrt(
        3.0 * d_left**2 + 3.0 * d_right**2 + 1.0 * d_adv**2 + 0.5 * d_area**2
    )


def cluster_glyphs(
    metrics: dict[str, GlyphMetrics],
    threshold: float = 0.35,
    templates: Optional[dict[str, list[str]]] = None,
) -> dict[str, list[str]]:
    """
    Group glyphs into classes by metric similarity.

    Uses template classes as seeds, then assigns unclassified glyphs to the
    nearest cluster if within *threshold*, otherwise creates a new class.
    """
    if templates is None:
        templates = LATIN_LEFT_CLASSES

    classified: set[str] = set()
    classes: dict[str, list[str]] = {}

    # Seed classes with template members that exist in the font
    for cls_name, members in templates.items():
        valid = [g for g in members if g in metrics]
        if valid:
            classes[cls_name] = valid
            classified.update(valid)

    # Assign remaining glyphs to nearest class
    unclassified = [g for g in metrics if g not in classified]
    for gname in unclassified:
        best_cls: Optional[str] = None
        best_dist = threshold
        for cls_name, members in classes.items():
            # Compare to centroid of class
            centroid = _class_centroid([metrics[m] for m in members])
            dist = _metric_distance(metrics[gname], centroid)
            if dist < best_dist:
                best_dist = dist
                best_cls = cls_name
        if best_cls:
            classes[best_cls].append(gname)
        else:
            classes[f"custom_{gname}"] = [gname]

    return classes


def _class_centroid(metrics_list: list[GlyphMetrics]) -> GlyphMetrics:
    """Compute average metrics for a group of glyphs."""
    n = max(len(metrics_list), 1)
    return GlyphMetrics(
        name="centroid",
        left_sb=sum(m.left_sb for m in metrics_list) / n,
        right_sb=sum(m.right_sb for m in metrics_list) / n,
        advance_width=sum(m.advance_width for m in metrics_list) / n,
        bbox=(0, 0, 0, 0),
        contour_area=sum(m.contour_area for m in metrics_list) / n,
        has_contours=True,
    )


# ---------------------------------------------------------------------------
# Kerning computation
# ---------------------------------------------------------------------------


def compute_pair_kern(
    left: GlyphMetrics,
    right: GlyphMetrics,
    min_kern: float = -200,
    max_kern: float = 200,
) -> float:
    """
    Calculate optimal kern value for a glyph pair.

    Heuristic: measure the visual gap between the right edge of the left glyph
    and the left edge of the right glyph when placed at their default advance
    positions.  A positive gap means the glyphs are too far apart → negative
    kern to tighten.  An overlap means they collide → positive kern to loosen.

    Formula:
        gap = right.left_sb - left.right_sb
        kern = -gap * weight

    The weight is modulated by the relative sizes of the glyphs so that
    narrow-narrow pairs get less adjustment than wide-wide pairs.
    """
    # Visual gap between glyphs at default spacing
    gap = right.left_sb - left.right_sb

    # Optical weight factor: larger glyphs need more adjustment
    avg_area = (left.contour_area + right.contour_area) / 2
    avg_adv = (left.advance_width + right.advance_width) / 2
    if avg_adv > 0:
        size_factor = min(avg_area / (avg_adv**2), 1.0)
    else:
        size_factor = 0.5

    # Base kern value: close the gap proportionally
    kern = -gap * (0.5 + 0.5 * size_factor)

    # Clamp to user-defined range
    kern = max(min_kern, min(max_kern, kern))

    return round(kern, 1)


def compute_class_kerning(
    left_classes: dict[str, list[str]],
    right_classes: dict[str, list[str]],
    metrics: dict[str, GlyphMetrics],
    min_kern: float = -200,
    max_kern: float = 200,
) -> list[ClassKernPair]:
    """
    Compute kerning values for every combination of left and right classes.

    Uses class centroids to determine a single kern value per class pair,
    which is the standard approach for OpenType class-based kerning.
    """
    pairs: list[ClassKernPair] = []

    left_centroids: dict[str, GlyphMetrics] = {}
    for cls_name, members in left_classes.items():
        left_centroids[cls_name] = _class_centroid(
            [metrics[m] for m in members if m in metrics]
        )

    right_centroids: dict[str, GlyphMetrics] = {}
    for cls_name, members in right_classes.items():
        right_centroids[cls_name] = _class_centroid(
            [metrics[m] for m in members if m in metrics]
        )

    for l_cls, l_centroid in left_centroids.items():
        for r_cls, r_centroid in right_centroids.items():
            value = compute_pair_kern(l_centroid, r_centroid, min_kern, max_kern)
            # Skip near-zero values to keep the kern table small
            if abs(value) < 1.0:
                continue
            pairs.append(
                ClassKernPair(left_class=l_cls, right_class=r_cls, value=value)
            )

    return pairs


def class_pairs_to_glyph_pairs(
    class_pairs: list[ClassKernPair],
    left_classes: dict[str, list[str]],
    right_classes: dict[str, list[str]],
) -> dict[tuple[str, str], float]:
    """
    Expand class-based kern pairs into individual glyph pairs.

    Returns a dict of (left_glyph, right_glyph) → kern_value.
    """
    glyph_pairs: dict[tuple[str, str], float] = {}

    for cp in class_pairs:
        left_glyphs = left_classes.get(cp.left_class, [])
        right_glyphs = right_classes.get(cp.right_class, [])
        for lg in left_glyphs:
            for rg in right_glyphs:
                glyph_pairs[(lg, rg)] = cp.value

    return glyph_pairs


# ---------------------------------------------------------------------------
# Apply kerning to UFO
# ---------------------------------------------------------------------------


def apply_kerning_to_ufo(
    font: Font,
    glyph_pairs: dict[tuple[str, float], float],
    *,
    strength: float = 1.0,
) -> None:
    """
    Write kerning data into a UFO Font object.

    Args:
        font: ufoLib2 Font instance (modified in place).
        glyph_pairs: dict of (left_glyph, right_glyph) → kern_value.
        strength: Multiplier from -1.0 to 1.0 to scale all kern values.
    """
    # Clear existing kerning
    font.kerning.clear()

    for (left, right), value in glyph_pairs.items():
        adjusted = value * strength
        if abs(adjusted) < 0.5:
            continue
        font.kerning[(left, right)] = round(adjusted, 1)


def reset_kerning(font: Font) -> None:
    """Remove all kerning from a UFO font."""
    font.kerning.clear()


# ---------------------------------------------------------------------------
# High-level auto-kern pipeline
# ---------------------------------------------------------------------------


@dataclass
class KerningResult:
    """Container for all auto-kerning outputs."""

    left_classes: dict[str, list[str]] = field(default_factory=dict)
    right_classes: dict[str, list[str]] = field(default_factory=dict)
    class_pairs: list[ClassKernPair] = field(default_factory=list)
    glyph_pairs: dict[tuple[str, str], float] = field(default_factory=dict)
    metrics: dict[str, GlyphMetrics] = field(default_factory=dict)


def auto_kern(
    font: Font,
    min_kern: float = -200,
    max_kern: float = 200,
    strength: float = 1.0,
    left_templates: Optional[dict[str, list[str]]] = None,
    right_templates: Optional[dict[str, list[str]]] = None,
) -> KerningResult:
    """
    Full auto-kerning pipeline:
    1. Extract metrics for all glyphs with contours.
    2. Classify glyphs into left and right classes.
    3. Compute class-based kerning pairs.
    4. Expand to glyph pairs and apply to the UFO.

    Returns a KerningResult with all intermediate data for inspection.
    """
    # Step 1: extract metrics
    metrics: dict[str, GlyphMetrics] = {}
    layer = font.layers.get("public.default", None)

    if layer is None or len(list(layer.keys())) == 0:
        # Fallback: try any layer that has glyphs
        available_layers = list(font.layers)
        logger.warning(
            "'public.default' layer not found or empty. "
            f"Available layers: {[l.name for l in available_layers]}. "
            "Falling back to first non-empty layer."
        )
        for fallback_layer in available_layers:
            if len(list(fallback_layer.keys())) > 0:
                layer = fallback_layer
                logger.info(f"Using layer: '{layer.name}' as fallback.")
                break

    if layer is not None:
        for glyph_name in layer.keys():
            glyph = layer[glyph_name]
            if len(glyph) > 0:  # only glyphs with contours
                metrics[glyph.name] = extract_metrics(glyph)

    if not metrics:
        logger.warning(
            "No glyphs with contours found in any layer. "
            "Ensure your UFO font has drawn glyph outlines. "
            "Auto-kerning cannot proceed with an empty or component-only font."
        )
        return KerningResult()

    # Step 2: classify
    left_classes = cluster_glyphs(metrics, templates=left_templates)
    right_classes = cluster_glyphs(metrics, templates=right_templates)

    # Step 3: compute class-based kerning
    class_pairs = compute_class_kerning(
        left_classes, right_classes, metrics, min_kern, max_kern
    )

    # Step 4: expand and apply
    glyph_pairs = class_pairs_to_glyph_pairs(class_pairs, left_classes, right_classes)
    apply_kerning_to_ufo(font, glyph_pairs, strength=strength)

    return KerningResult(
        left_classes=left_classes,
        right_classes=right_classes,
        class_pairs=class_pairs,
        glyph_pairs=glyph_pairs,
        metrics=metrics,
    )

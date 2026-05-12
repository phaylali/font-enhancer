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
    "O_left": ["O", "C", "Q", "G", "D"],
    "o_left": ["c", "e", "o", "d", "q", "g"],
    "H_left": ["H", "I", "B", "E", "M", "N"],
    "h_left": ["h", "b", "l", "i", "m", "n", "p", "r", "u"],
    "V_left": ["V", "W", "Y"],
    "v_left": ["v", "w", "y"],
    "A_left": ["A"],
    "a_left": ["a"],
    "T_left": ["T"],
    "F_left": ["F"],
    "P_left": ["P"],
    "L_left": ["L"],
    "R_left": ["R"],
    "K_left": ["K", "k", "X", "x"],
    "slash_left": ["slash", "backslash", "/"],
}

LATIN_RIGHT_CLASSES: dict[str, list[str]] = {
    "O_right": ["O", "C", "Q", "G"],
    "o_right": ["c", "e", "o", "b", "p", "d", "q"],
    "H_right": ["H", "I", "B", "E", "F", "D", "M", "N", "P", "R"],
    "h_right": ["h", "l", "i", "m", "n", "u"],
    "V_right": ["V", "W", "Y"],
    "v_right": ["v", "w", "y"],
    "A_right": ["A"],
    "a_right": ["a", "s"],
    "T_right": ["T"],
    "J_right": ["J", "j"],
    "K_right": ["K", "k", "X", "x"],
    "slash_right": ["slash", "backslash", "/"],
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

    # --- 6 profile anchor points (absolute X in font units) ---
    # Bounding box divided into 3 equal vertical zones; each stores the
    # leftmost / rightmost ink X found within that zone.
    left_top: float = 0.0    # leftmost X in top zone
    left_mid: float = 0.0    # leftmost X in middle zone
    left_bot: float = 0.0    # leftmost X in bottom zone
    right_top: float = 0.0   # rightmost X in top zone
    right_mid: float = 0.0   # rightmost X in middle zone
    right_bot: float = 0.0   # rightmost X in bottom zone


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
# Zone-profile helpers
# ---------------------------------------------------------------------------


def extract_zone_profile(
    glyph,
    bbox: tuple[float, float, float, float],
) -> tuple[float, float, float, float, float, float]:
    """
    Divide the glyph bounding box into three equal vertical zones and return
    the leftmost / rightmost ink X coordinate found in each zone.

    Returns:
        (left_top, left_mid, left_bot, right_top, right_mid, right_bot)

    If a zone contains no contour points, the full bounding-box extreme is
    used as a conservative fallback so downstream calculations stay valid.
    """
    xmin, ymin, xmax, ymax = bbox
    h = ymax - ymin
    if h <= 0:
        return xmin, xmin, xmin, xmax, xmax, xmax

    # Equal-thirds zone boundaries
    bot_lo, bot_hi = ymin,             ymin + h / 3
    mid_lo, mid_hi = ymin + h / 3,     ymin + 2 * h / 3
    top_lo, top_hi = ymin + 2 * h / 3, ymax

    # Collect every point coordinate from every contour
    all_pts: list[tuple[float, float]] = [
        (pt.x, pt.y)
        for contour in glyph
        for pt in contour
    ]

    def _zone_x(y_lo: float, y_hi: float) -> tuple[float, float]:
        xs = [x for x, y in all_pts if y_lo <= y <= y_hi]
        return (min(xs), max(xs)) if xs else (xmin, xmax)

    top_l, top_r = _zone_x(top_lo, top_hi)
    mid_l, mid_r = _zone_x(mid_lo, mid_hi)
    bot_l, bot_r = _zone_x(bot_lo, bot_hi)

    return top_l, mid_l, bot_l, top_r, mid_r, bot_r


# ---------------------------------------------------------------------------
# Metric extraction
# ---------------------------------------------------------------------------


def extract_metrics(glyph: Glyph) -> GlyphMetrics:
    """
    Extract sidebearings, advance width, bounding box, and 6-point zone
    profile from a glyph.

    The 6 profile fields (left/right_top/mid/bot) store the leftmost /
    rightmost ink X coordinate found within each equal-thirds vertical zone
    of the bounding box.  These are used by compute_pair_kern() to calculate
    the gap between adjacent glyphs at three heights, giving accurate optical
    kerning for diagonals (V, W, A) and arms (T, F, L) without manual tuning.
    """
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
            # Populate 6-point profile
            (
                m.left_top, m.left_mid, m.left_bot,
                m.right_top, m.right_mid, m.right_bot,
            ) = extract_zone_profile(glyph, bbox)
        else:
            m.left_sb = 0
            m.right_sb = glyph.width
            # Profile defaults to full-width extremes
            m.left_top = m.left_mid = m.left_bot = 0.0
            m.right_top = m.right_mid = m.right_bot = glyph.width
    else:
        m.left_sb = 0
        m.right_sb = glyph.width

    return m


# ---------------------------------------------------------------------------
# Auto-classification
# ---------------------------------------------------------------------------


def _metric_distance(a: GlyphMetrics, b: GlyphMetrics) -> float:
    """
    Weighted Euclidean distance between two glyph metric profiles.

    Incorporates both the legacy sidebearing scalars and the 6-point zone
    profile so that glyphs with similar edge *shapes* (not just overall widths)
    are clustered together.  This improves class quality for diagonals and
    arms which have very different top/bottom edge positions.
    """
    avg_adv = max((a.advance_width + b.advance_width) / 2, 1.0)

    d_left  = (a.left_sb  - b.left_sb)  / avg_adv
    d_right = (a.right_sb - b.right_sb) / avg_adv
    d_adv   = (a.advance_width - b.advance_width) / avg_adv
    d_area  = (a.contour_area  - b.contour_area)  / (avg_adv ** 2 + 1)

    # 6-point profile deltas (left edge shape)
    d_lt = (a.left_top - b.left_top) / avg_adv
    d_lm = (a.left_mid - b.left_mid) / avg_adv
    d_lb = (a.left_bot - b.left_bot) / avg_adv
    # 6-point profile deltas (right edge shape)
    d_rt = (a.right_top - b.right_top) / avg_adv
    d_rm = (a.right_mid - b.right_mid) / avg_adv
    d_rb = (a.right_bot - b.right_bot) / avg_adv

    return math.sqrt(
        2.0 * d_left ** 2  + 2.0 * d_right ** 2
        + 1.0 * d_adv ** 2 + 0.5 * d_area ** 2
        + 1.5 * (d_lt ** 2 + d_lm ** 2 + d_lb ** 2)   # left profile shape
        + 1.5 * (d_rt ** 2 + d_rm ** 2 + d_rb ** 2)   # right profile shape
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
    """Compute average metrics (including 6-point profile) for a glyph class."""
    n = max(len(metrics_list), 1)
    def _avg(attr: str) -> float:
        return sum(getattr(m, attr) for m in metrics_list) / n
    return GlyphMetrics(
        name="centroid",
        left_sb=_avg("left_sb"),
        right_sb=_avg("right_sb"),
        advance_width=_avg("advance_width"),
        bbox=(0, 0, 0, 0),
        contour_area=_avg("contour_area"),
        has_contours=True,
        left_top=_avg("left_top"),
        left_mid=_avg("left_mid"),
        left_bot=_avg("left_bot"),
        right_top=_avg("right_top"),
        right_mid=_avg("right_mid"),
        right_bot=_avg("right_bot"),
    )


# ---------------------------------------------------------------------------
# Kerning computation
# ---------------------------------------------------------------------------


def compute_pair_kern(
    left: GlyphMetrics,
    right: GlyphMetrics,
    left_cls: str,
    right_cls: str,
    min_kern: float = -200,
    max_kern: float = 200,
) -> float:
    """
    Calculate the optimal kern value for a glyph pair using 6-point profile
    kerning.

    For each of the three vertical zones (top, center, bottom), the visual gap
    between the two glyphs when placed side-by-side is:

        gap_zone = (left.advance_width - left.right_zone) + right.left_zone

    The first term is the white space to the RIGHT of the left glyph's ink at
    that height.  The second term is the white space to the LEFT of the right
    glyph's ink at that height.  Together they give the total visual gap at
    that vertical position.

    We use the **minimum gap across all three zones** (the tightest point)
    to drive the kern value:

        kern = ideal_gap - min_gap

    This naturally handles diagonals (V, W, A), arms (T, F, L), and rounded
    glyphs (O, C) without any hard-coded tuck table — the geometry does the
    work.
    """
    # Gap at each vertical zone
    gap_top = (left.advance_width - left.right_top) + right.left_top
    gap_mid = (left.advance_width - left.right_mid) + right.left_mid
    gap_bot = (left.advance_width - left.right_bot) + right.left_bot

    # Baseline neutral gap — what the font's existing sidebearings already
    # create when no kern is applied.  For uniform glyphs (H, n, o) this
    # equals the weighted zone gap, so kern → 0.
    baseline_gap = left.right_sb + right.left_sb

    # Weighted zone gap: midpoint carries the most optical weight.
    # Top and bottom each contribute 25 % so that arms (T, F) and
    # diagonals (V, A, W) influence the result without dominating.
    weighted_gap = 0.25 * gap_top + 0.50 * gap_mid + 0.25 * gap_bot

    # Kern = correction that brings weighted_gap back towards baseline.
    # Damping factor (0.4) prevents over-kerning; the remaining 60 % of
    # the gap difference is left for the designer to fine-tune.
    kern = (baseline_gap - weighted_gap) * 0.4

    # Safety: never kern so tight that the minimum zone gap goes negative
    # (that would cause ink overlap at some height).
    min_gap = min(gap_top, gap_mid, gap_bot)
    kern = max(kern, -min_gap)

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
            value = compute_pair_kern(l_centroid, r_centroid, l_cls, r_cls, min_kern, max_kern)
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


def is_latin_glyph(glyph: Glyph) -> bool:
    """Check if a glyph belongs to the Latin script or general punctuation."""
    if not glyph.unicodes:
        # Check name for unencoded glyphs
        gn = glyph.name.lower()
        if "arab" in gn or "tifinagh" in gn:
            return False
        import re
        if re.match(r'^[a-z]+$', gn) or gn in ["period", "comma", "hyphen", "space", "exclam", "question"]:
            return True
        return False
        
    for u in glyph.unicodes:
        # Basic Latin, Latin-1, Latin Extended A & B, General Punctuation
        if u <= 0x024F or (0x2000 <= u <= 0x206F):
            return True
    return False

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
            if len(glyph) > 0 and is_latin_glyph(glyph):  # only Latin glyphs with contours
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

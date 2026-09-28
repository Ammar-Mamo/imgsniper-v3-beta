"""
Centralized image codec with optional RAW and HEIC support.

Pillow alone cannot decode HEIC/HEIF or most camera RAW formats (CR2, NEF,
ARW...). This module provides a single entry point -- ``open_image()`` --
that tries standard Pillow first and falls back to ``rawpy`` for camera RAW
when it is installed. ``pillow-heif``, when installed, registers itself as a
Pillow plugin so HEIC/HEIF open through the normal Pillow path.

Both extras are OPTIONAL: if absent, undecodable files return None and the
caller counts/announces them -- nothing is ever silently swallowed.

Usage:
    from ...utils.helpers.image_codec import open_image, codec_status

    img = open_image(path)          # -> PIL Image or None
    if img is not None:
        ...
        img.close()

    status = codec_status()         # {'heif': True, 'raw': True}
"""

import logging
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image

logger = logging.getLogger("imgsniper.codec")

# ---------------------------------------------------------------------------
# Probe optional dependencies once at import time
# ---------------------------------------------------------------------------
_HEIF_AVAILABLE = False
_RAWPY_AVAILABLE = False

try:
    import pillow_heif  # type: ignore[import-untyped]

    # Register HEIF opener so Image.open() handles .heic/.heif natively.
    pillow_heif.register_heif_opener()
    try:
        pillow_heif.register_avif_opener()
    except AttributeError:
        pass  # older pillow-heif without a separate AVIF registration
    _HEIF_AVAILABLE = True
except ImportError:
    pass

try:
    import rawpy  # type: ignore[import-untyped]

    _RAWPY_AVAILABLE = True
except ImportError:
    pass

# Formats that require rawpy (not handled by Pillow even with plugins)
RAW_EXTENSIONS = frozenset({
    ".cr2", ".cr3", ".nef", ".nrw", ".arw", ".dng", ".orf", ".rw2",
    ".pef", ".srw", ".x3f", ".raf", ".raw",
})

# Formats handled by pillow-heif after registration
HEIF_EXTENSIONS = frozenset({".heic", ".heif", ".avif"})


def codec_status() -> dict:
    """Return availability of optional codecs for UI/log reporting."""
    return {
        "heif": _HEIF_AVAILABLE,
        "raw": _RAWPY_AVAILABLE,
    }


def open_image_with_reason(file_path, mode: str = "RGB") -> Tuple[Optional[Image.Image], Optional[str]]:
    """
    Open an image file; return ``(image, None)`` on success or ``(None, reason)``.

    ``reason`` is one of:

    * ``'missing_codec'`` -- a RAW/HEIF file whose OPTIONAL decoder
      (rawpy / pillow-heif) is not installed. The file itself is NOT corrupt.
    * ``'decode_error'``  -- the decoder exists (or the format is standard)
      but the file could not be read: damaged, truncated, or a mismatched
      extension.

    Resolution order:
      1. Camera RAW extensions -> rawpy (when installed). rawpy decodes the
         sensor data directly, which is more faithful than any embedded
         preview.
      2. Standard ``Image.open()`` -- covers JPEG/PNG/WebP/BMP/TIFF/GIF/ICO/
         PSD and HEIC/HEIF/AVIF when pillow-heif is installed and registered.

    The returned image is already converted to *mode* (default RGB) and fully
    loaded, so the caller does not need a context manager. It is the caller's
    job to count/announce skipped files.
    """
    path = Path(file_path)
    ext = path.suffix.lower()

    # --- Camera RAW: rawpy is the only reliable decoder --------------------
    if ext in RAW_EXTENSIONS:
        if not _RAWPY_AVAILABLE:
            logger.debug("RAW file skipped (rawpy not installed): %s", path.name)
            return None, 'missing_codec'
        try:
            import rawpy

            with rawpy.imread(str(path)) as raw:
                rgb_array = raw.postprocess(use_camera_wb=True, output_bps=8)
            img = Image.fromarray(rgb_array)
            # PIL images from numpy have no .format; tag it for reports.
            img.format = f"RAW({ext.lstrip('.').upper()})"  # type: ignore[attr-defined]
            if mode and img.mode != mode:
                img = img.convert(mode)
            return img, None
        except Exception as exc:
            logger.debug("rawpy failed for %s: %s", path.name, exc)
            return None, 'decode_error'

    # --- Everything else: Pillow (incl. HEIC via pillow-heif plugin) --------
    try:
        with Image.open(path) as src:
            fmt = src.format
            img = src.convert(mode) if (mode and src.mode != mode) else src.copy()
            img.load()
        # Preserve the original container format after copy/convert.
        img.format = fmt  # type: ignore[attr-defined]
        return img, None
    except Exception as exc:
        logger.debug("Pillow could not open %s: %s", path.name, exc)
        if ext in HEIF_EXTENSIONS and not _HEIF_AVAILABLE:
            # Pillow alone cannot decode HEIC/HEIF: the absence of the
            # optional plugin is 'unsupported', not corruption.
            return None, 'missing_codec'
        return None, 'decode_error'


def open_image(file_path, mode: str = "RGB") -> Optional[Image.Image]:
    """Backwards-friendly wrapper: return the image only, or None.

    Callers that must distinguish 'missing_codec' from 'decode_error' --
    e.g. the corruption scan, which must NOT flag an undecodable-format file
    as corrupted -- use ``open_image_with_reason()`` directly.
    """
    img, _reason = open_image_with_reason(file_path, mode=mode)
    return img


def read_dimensions(file_path) -> Optional[tuple]:
    """Return (width, height) WITHOUT decoding full pixels, or None.

    Header-level read: RAW via rawpy sizes (no demosaic), everything else
    via Pillow's lazy open (HEIC works when pillow-heif is registered).
    """
    path = Path(file_path)
    ext = path.suffix.lower()
    if ext in RAW_EXTENSIONS:
        if not _RAWPY_AVAILABLE:
            return None
        try:
            import rawpy

            with rawpy.imread(str(path)) as raw:
                sizes = raw.sizes
                return (int(sizes.width), int(sizes.height))
        except Exception as exc:
            logger.debug("rawpy sizes failed for %s: %s", path.name, exc)
            return None
    try:
        with Image.open(path) as src:
            return src.size
    except Exception as exc:
        logger.debug("Could not read dimensions of %s: %s", path.name, exc)
        return None


def probe_image(file_path) -> Optional[dict]:
    """Header-level metadata {'width','height','format','mode'} or None.

    Used by report info extraction so RAW/HEIC rows show real dimensions
    and format instead of 0x0/Unknown. RAW reports format 'RAW(EXT)'.
    """
    path = Path(file_path)
    ext = path.suffix.lower()
    if ext in RAW_EXTENSIONS:
        dims = read_dimensions(path)
        if dims is None:
            return None
        return {
            'width': dims[0],
            'height': dims[1],
            'format': f"RAW({ext.lstrip('.').upper()})",
            'mode': 'sensor',
        }
    try:
        with Image.open(path) as src:
            return {
                'width': src.width,
                'height': src.height,
                'format': src.format or ext.lstrip('.').upper(),
                'mode': src.mode,
            }
    except Exception as exc:
        logger.debug("Could not probe %s: %s", path.name, exc)
        return None


def can_decode_extension(ext: str) -> bool:
    """
    Return True if the given extension (with leading dot) can be decoded
    by the currently installed set of codecs.
    """
    ext = ext.lower()
    if ext in HEIF_EXTENSIONS:
        return _HEIF_AVAILABLE
    if ext in RAW_EXTENSIONS:
        return _RAWPY_AVAILABLE
    # Everything else is assumed to be handled by base Pillow.
    return True


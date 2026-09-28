"""
Image information extraction utilities
"""
# وحدة التقارير - ينشئ ملفات HTML وإحصائيات مفصلة


from datetime import datetime
from pathlib import Path
from typing import Dict, Any
from ...utils.helpers.date_extractor import date_extractor
from ...utils.helpers.image_codec import probe_image
from ...core.config import config
from ...core.i18n.i18n import i18n


class ImageInfoExtractor:
    """Extract detailed information about image files."""
    
    def get_detailed_image_info(self, file_path: str) -> Dict[str, Any]:
        """Get detailed information about an image file."""
        try:
            path = Path(file_path)
            if not path.exists():
                return {"error": "File not found"}
            
            # Basic ملف info
            stat = path.stat()
            file_size = stat.st_size
            
            # Image بُعدs and تنسيق
            try:
                probed = probe_image(file_path)
                if probed:
                    width = probed['width']
                    height = probed['height']
                    format_type = probed['format']
                    mode = probed['mode']
                else:
                    width = height = 0
                    format_type = "Unknown"
                    mode = "Unknown"
            except Exception:
                width = height = 0
                format_type = "Unknown"
                mode = "Unknown"
            
            # Date extraction.
            #
            # Audit finding P2-13: this read the FILENAME only, so a
            # photo whose date lives in EXIF -- the normal case for a
            # camera file named IMG_1234.jpg -- was reported as
            # "Unknown" even though the selection engine had already
            # used that very EXIF date to decide which copy to keep.
            # The report therefore could not justify the decision it
            # was documenting.
            #
            # get_best_date() merges EXIF and filename exactly as the
            # engine does, and the winning source is reported next to
            # the value so the user can see where the date came from.
            date_priority = config.get('priorities.date_priority', 'oldest')
            extracted_date, date_source = date_extractor.get_best_date(
                file_path, date_priority
            )
            filename_importance = date_extractor.get_filename_importance_score(path.name)
            
            # Audit round 5 (issue #14/#239): a date extracted from the
            # FILENAME is built as datetime(y, m, d) -- always midnight.
            # Printed bare, it made a same-day EXIF timestamp look "newer"
            # and produced misleading "older extracted date" reasons, so
            # day-level precision is flagged here and annotated in reports.
            date_only = bool(
                extracted_date
                and date_source == 'filename'
                and (extracted_date.hour, extracted_date.minute, extracted_date.second) == (0, 0, 0)
            )
            
            return {
                "name": path.name,
                "size_bytes": file_size,
                "size_mb": round(file_size / (1024 * 1024), 2),
                "width": width,
                "height": height,
                "resolution": width * height,
                "format": format_type,
                "mode": mode,
                "extracted_date": extracted_date.strftime('%Y-%m-%d %H:%M:%S') if extracted_date else "Unknown",
                "date_source": date_source,
                "date_only": date_only,
                "filename_importance": filename_importance,
                "modified_time": datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                "created_time": datetime.fromtimestamp(stat.st_ctime).strftime('%Y-%m-%d %H:%M:%S')
            }
        except Exception as e:
            return {"error": str(e)}


def format_extracted_date(info: Dict[str, Any]) -> str:
    """Render extracted_date, annotating filename dates that carry no time.

    A filename like "IMG_20220720.jpg" yields a date built as
    datetime(2022, 7, 20) -- midnight is an artifact of day-level precision,
    NOT a real capture time. The annotation stops readers from comparing it
    against real EXIF timestamps of the same day (audit round 5, #14/#239).
    """
    value = info.get('extracted_date', 'Unknown')
    if info.get('date_only'):
        suffix = None
        try:
            suffix = i18n.get('reports.date_only_suffix')
        except Exception:
            suffix = None
        if not suffix or str(suffix).startswith('[Missing'):
            suffix = ' (date only - no time in filename)'
        value = f"{value}{suffix}"
    return value
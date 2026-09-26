"""
Image information extraction utilities
"""
# وحدة التقارير - ينشئ ملفات HTML وإحصائيات مفصلة


from datetime import datetime
from pathlib import Path
from typing import Dict, Any
from PIL import Image

from ...utils.helpers.date_extractor import date_extractor


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
                with Image.open(file_path) as img:
                    width, height = img.size
                    format_type = img.format
                    mode = img.mode
            except Exception:
                width = height = 0
                format_type = "Unknown"
                mode = "Unknown"
            
            # Date extrعمل
            extracted_date = date_extractor.extract_date_from_filename(path.name)
            filename_importance = date_extractor.get_filename_importance_score(path.name)
            
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
                "filename_importance": filename_importance,
                "modified_time": datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                "created_time": datetime.fromtimestamp(stat.st_ctime).strftime('%Y-%m-%d %H:%M:%S')
            }
        except Exception as e:
            return {"error": str(e)}
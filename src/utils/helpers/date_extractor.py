"""
Advanced date extraction from filenames and EXIF data
استخراج التاريخ المتقدم من أسماء الملفات وبيانات EXIF
"""
# وحدة مساعدة - دوال مشتركة ومساعدة للوحدات الأخرى


import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple
from PIL import Image
from PIL.ExifTags import TAGS

class DateExtractor:
    """Advanced date extraction from filenames and EXIF data."""
    
    def __init__(self):
        # Arabic رقمs خريطةping
        self.arabic_to_english = {
            '٠': '0', '١': '1', '٢': '2', '٣': '3', '٤': '4',
            '٥': '5', '٦': '6', '٧': '7', '٨': '8', '٩': '9'
        }
        
        # Date patterns. NOTE: the filename is lower-cased before matching,
        # so patterns must NOT contain upper-case letters (the previous
        # IMG_/Screenshot_/Snapchat_/DSC_/VID_ patterns were dead code that
        # could never match). The generic patterns below already capture the
        # date digits from ANY filename, including those prefixed formats.
        self.date_patterns = [
            # YYYY-MM-DD (and _ . / separators)
            r'(\d{4})[_\-\.\/](\d{1,2})[_\-\.\/](\d{1,2})',
            # DD-MM-YYYY (and _ . / separators)
            r'(\d{1,2})[_\-\.\/](\d{1,2})[_\-\.\/](\d{4})',
            # YYYYMMDD
            r'(\d{4})(\d{2})(\d{2})',
            # DDMMYYYY
            r'(\d{2})(\d{2})(\d{4})',
            # Generic YYYY_MM_DD anywhere in the filename
            r'.*(\d{4})[_\-\.\/](\d{1,2})[_\-\.\/](\d{1,2}).*',
            # Generic YYYYMMDD anywhere in the filename
            r'.*(\d{4})(\d{2})(\d{2}).*',
        ]
        
        # Time نمطs for more دقة
        self.time_patterns = [
            r'(\d{1,2})[_\-\.](\d{2})[_\-\.](\d{2})',  # HH:MM:SS
            r'(\d{1,2})(\d{2})(\d{2})',  # HHMMSS
        ]
        
        # Fileاسم أهمية رتبةing
        self.filename_importance = {
            'recovered': 1,  # Lowest importance
            'copy': 2,
            'duplicate': 2,
            'backup': 3,
            'temp': 3,
            'tmp': 3,
            'cache': 3,
            'thumbnail': 4,
            'thumb': 4,
            'preview': 4,
            'img': 7,
            'image': 7,
            'photo': 7,
            'pic': 7,
            'picture': 7,
            'dsc': 8,
            'vid': 8,
            'video': 8,
            'screenshot': 6,
            'snapchat': 6,
            'whatsapp': 6,
            'camera': 9,
            'original': 10,  # Highest importance
            # Add نمطs for copied/modified ملفات (منخفضer أهمية)
            ' (1)': 2,  # File (1).jpg
            ' (2)': 2,  # File (2).jpg
            ' (3)': 2,  # File (3).jpg
            ' (4)': 2,  # File (4).jpg
            ' (5)': 2,  # File (5).jpg
            ' (6)': 2,  # File (6).jpg
            ' (7)': 2,  # File (7).jpg
            ' (8)': 2,  # File (8).jpg
            ' (9)': 2,  # File (9).jpg
            ' - copy': 2,  # File - copy.jpg
            '_copy': 2,  # File_copy.jpg
            'new ': 3,  # New File.jpg
            'edited': 4,  # Edited file
            'modified': 4,  # Modified file
        }
    
    def normalize_arabic_numbers(self, text: str) -> str:
        """Convert Arabic numerals to English numerals."""
        for arabic, english in self.arabic_to_english.items():
            text = text.replace(arabic, english)
        return text
    
    def extract_date_from_filename(self, filename: str) -> Optional[datetime]:
        """Extract date from filename using various patterns."""
        filename = self.normalize_arabic_numbers(filename.lower())
        
        for pattern in self.date_patterns:
            match = re.search(pattern, filename)
            if match:
                groups = match.groups()
                
                try:
                    if len(groups) == 3:
                        # Determine if it's YYYY-MM-DD or DD-MM-YYYY
                        if len(groups[0]) == 4:  # YYYY-MM-DD
                            year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
                        elif len(groups[2]) == 4:  # DD-MM-YYYY
                            day, month, year = int(groups[0]), int(groups[1]), int(groups[2])
                        else:
                            continue
                        
                        # التحقق من صحة تاريخ
                        if 1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31:
                            return datetime(year, month, day)
                            
                except (ValueError, TypeError):
                    continue
        
        return None
    
    def extract_date_from_exif(self, image_path: str) -> Optional[datetime]:
        """
        Extract the capture date from EXIF data.

        Tags are checked in PRIORITY order — DateTimeOriginal (the actual
        capture time) first, then DateTimeDigitized, then the generic
        DateTime (which is often only the last-modified time). The previous
        version returned whichever tag happened to appear first while
        iterating the EXIF dict, so it could pick a less accurate date.
        """
        try:
            with Image.open(image_path) as img:
                tag_values = self._read_exif_tag_values(img)
                return self._pick_date_from_tags(tag_values)
        except Exception:
            return None

    def _read_exif_tag_values(self, img) -> dict:
        """
        Build a flattened {tag_name: string_value} map from an open PIL image.

        EXIF date tags live in different IFDs: DateTime is in the 0th IFD,
        while DateTimeOriginal / DateTimeDigitized are in the Exif sub-IFD
        (0x8769). img._getexif() returns a flattened dict that already merges
        both, so it is used first. If unavailable, the public getexif() API is
        used and the Exif sub-IFD is merged in explicitly so DateTimeOriginal
        is never missed.
        """
        tag_values = {}

        raw = None
        try:
            raw = img._getexif()
        except Exception:
            raw = None

        if raw:
            for tag_id, value in raw.items():
                tag_name = TAGS.get(tag_id, tag_id)
                if isinstance(value, str):
                    tag_values[tag_name] = value
            return tag_values

        # Fallback: public API + explicit Exif sub-IFD merge
        try:
            exif = img.getexif()
            for tag_id, value in exif.items():
                tag_name = TAGS.get(tag_id, tag_id)
                if isinstance(value, str):
                    tag_values[tag_name] = value
            try:
                for tag_id, value in exif.get_ifd(0x8769).items():
                    tag_name = TAGS.get(tag_id, tag_id)
                    if isinstance(value, str):
                        tag_values[tag_name] = value
            except Exception:
                pass
        except Exception:
            pass

        return tag_values

    def _pick_date_from_tags(self, tag_values: dict) -> Optional[datetime]:
        """
        Pick the best capture date from a {tag_name: value} map by priority:
        DateTimeOriginal > DateTimeDigitized > DateTime. Keeping this separate
        makes the priority logic unit-testable without needing a real image.
        """
        date_tag_priority = ['DateTimeOriginal', 'DateTimeDigitized', 'DateTime']
        date_formats = ('%Y:%m:%d %H:%M:%S', '%Y-%m-%d %H:%M:%S')

        for tag_name in date_tag_priority:
            value = tag_values.get(tag_name)
            if not value:
                continue
            for fmt in date_formats:
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    continue
        return None
    
    def get_filename_importance_score(self, filename: str) -> int:
        """
        Get an importance score (1-11) based on filename patterns.

        Matching is word-boundary aware: a keyword only matches when it
        appears as a whole token, so 'pic' no longer matches 'epic' or
        'picnic', and 'temp' no longer matches 'attempt' or 'Temple'.
        Patterns that carry their own delimiters (e.g. ' (1)', '_copy',
        'new ') are still matched as literal substrings.
        """
        filename_lower = filename.lower()

        # Default score for an ordinary filename
        max_score = 5

        # Collect matching patterns using word-boundary-aware matching
        found_patterns = []
        for pattern, score in self.filename_importance.items():
            if self._pattern_matches(filename_lower, pattern):
                found_patterns.append((pattern, score))

        # If patterns matched, the most specific one wins (longest pattern)
        if found_patterns:
            found_patterns.sort(key=lambda x: len(x[0]), reverse=True)
            max_score = found_patterns[0][1]

        # Penalty for obvious copies/duplicates — cap the score at 3
        copy_markers = [' (', '_copy', '- copy', 'duplicate']
        if any(self._pattern_matches(filename_lower, m) for m in copy_markers):
            max_score = min(max_score, 3)

        # Small bonus (+1) for clean names: no numbered copy suffix and not
        # already flagged as 'original'/'camera' (which keep their exact score)
        numbered = [' (' + str(i) + ')' for i in range(1, 10)]
        if not any(p in filename_lower for p in numbered):
            if not self._pattern_matches(filename_lower, 'original') and \
               not self._pattern_matches(filename_lower, 'camera'):
                max_score += 1

        return max_score

    def _pattern_matches(self, filename_lower: str, pattern: str) -> bool:
        """
        Word-boundary-aware pattern matching for filename keywords.

        - Purely alphabetic keywords ('pic', 'temp', 'photo', 'img', ...)
          are matched as whole tokens. The filename is split on delimiters
          (_, -, ., whitespace, parentheses, digits and any non a-z char),
          so 'img' matches 'img_1234' but 'pic' does NOT match 'epic' or
          'picnic', and 'temp' does NOT match 'attempt' or 'Temple'.
        - Patterns containing non-alphabetic characters (' (1)', '_copy',
          ' - copy', 'new ') are matched as literal substrings, because
          their own delimiters already provide the needed boundaries.
        """
        if pattern.isalpha():
            tokens = re.split(r'[^a-z]+', filename_lower)
            return pattern in tokens
        return pattern in filename_lower
    
    def get_best_date(self, image_path: str, date_priority: str = 'oldest') -> Tuple[Optional[datetime], str]:
        """
        Get the best date from filename and EXIF, considering priority.
        Returns (date, source) where source is 'filename', 'exif', or 'none'
        """
        filename = Path(image_path).name
        
        # استخراج تاريخs from both مصدرs
        filename_date = self.extract_date_from_filename(filename)
        exif_date = self.extract_date_from_exif(image_path)
        
        # If only واحد مصدر has a تاريخ, use it
        if filename_date and not exif_date:
            return filename_date, 'filename'
        elif exif_date and not filename_date:
            return exif_date, 'exif'
        elif not filename_date and not exif_date:
            return None, 'none'
        
        # Both مصدرs have تاريخs - compare and choose based on أولوية
        if date_priority == 'oldest':
            if filename_date <= exif_date:
                return filename_date, 'filename'
            else:
                return exif_date, 'exif'
        else:  # جديدest
            if filename_date >= exif_date:
                return filename_date, 'filename'
            else:
                return exif_date, 'exif'
    
    def compare_images_by_date(self, image1_path: str, image2_path: str, 
                              date_priority: str = 'oldest') -> int:
        """
        Compare two images by date.
        Returns: -1 if image1 is better, 1 if image2 is better, 0 if equal
        """
        date1, source1 = self.get_best_date(image1_path, date_priority)
        date2, source2 = self.get_best_date(image2_path, date_priority)
        
        # If واحد has no تاريخ, the other فوزs
        if date1 and not date2:
            return -1
        elif date2 and not date1:
            return 1
        elif not date1 and not date2:
            # مقارنة by ملفاسم أهمية
            score1 = self.get_filename_importance_score(Path(image1_path).name)
            score2 = self.get_filename_importance_score(Path(image2_path).name)
            
            if score1 > score2:
                return -1
            elif score2 > score1:
                return 1
            else:
                return 0
        
        # Both have تاريخs - compare based on أولوية
        if date_priority == 'oldest':
            if date1 < date2:
                return -1
            elif date1 > date2:
                return 1
        else:  # جديدest
            if date1 > date2:
                return -1
            elif date1 < date2:
                return 1
        
        # Dates are equal - compare by ملفاسم أهمية
        score1 = self.get_filename_importance_score(Path(image1_path).name)
        score2 = self.get_filename_importance_score(Path(image2_path).name)
        
        if score1 > score2:
            return -1
        elif score2 > score1:
            return 1
        else:
            return 0

# Global مثيل
date_extractor = DateExtractor()
"""
Advanced date extraction from filenames and EXIF data
استخراج التاريخ المتقدم من أسماء الملفات وبيانات EXIF
"""
# وحدة مساعدة - دوال مشتركة ومساعدة للوحدات الأخرى


import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple
from PIL import Image
from PIL.ExifTags import TAGS

# ---------------------------------------------------------------------------
# Round 16: numbered-copy detection, compiled once at import time.
#
# ' (N)' for ANY N. Windows, browsers and recovery tools all append ' (N)' when
# they save another copy of a file, and on a large recovery N grows far past 9
# -- the user's own corpus contains names such as 'copy (99999999)'. The old
# list stopped at ' (9)', so ' (10)' and above escaped the penalty ENTIRELY and
# scored as a clean name: 'photo (10).jpg' was worth 8 while 'photo (9).jpg'
# was worth 3. Only PURE digits inside the parentheses match, so a real
# qualifier such as '(2024-01-01)' or '(12x16)' is still left alone.
_NUMBERED_COPY_RE = re.compile(r'\(\s*\d+\s*\)')

# Arabic 'نسخة <digits>' -- and the very common 'نسخه' spelling variant (ه
# instead of ة). The PARENTHESISED Arabic form 'نسخة (٢٢١٩٧٣٦٠١)' needs no
# pattern of its own: it is caught by _NUMBERED_COPY_RE as soon as the
# Arabic-Indic digits are normalised to ASCII.
_ARABIC_NUMBERED_COPY_RE = re.compile(r'نسخ[هة]\s*\d+')

# Invisible bidirectional marks that Windows embeds in Arabic filenames, e.g.
# '‏نسخة (٢) من file.txt' carries a RIGHT-TO-LEFT MARK (U+200F). Neither a
# digit regex nor an Arabic substring can match through them, so they are
# stripped for MATCHING ONLY -- the score itself is never rewritten.
_BIDI_MARKS_RE = re.compile('[\u200e\u200f\u202a-\u202e\u2066-\u2069]')


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
            # Round 16: Arabic copy wording. Windows' Arabic locale names a
            # duplicate 'نسخة' / 'نسخة (٢) من ...' / 'ملف - نسخة', and none of
            # it was detected before, so an Arabic-locale library kept its
            # copies. Weighted exactly like 'copy'. Both spellings are listed
            # because 'نسخه' (ه instead of ة) is extremely common in real
            # filenames. These are matched as SUBSTRINGS, not tokens -- see
            # _pattern_matches, whose token split is [^a-z]+ and would
            # otherwise destroy every Arabic character and never match.
            'نسخة': 2,
            'نسخه': 2,
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
            'camera': 8,
            'original': 8,
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
            except Exception as e:
                # Audit P2-20: was a silent "pass". The Exif sub-IFD is where
                # DateTimeOriginal lives, so losing it silently downgrades the
                # date source to "filename" and can change WHICH image a group
                # keeps. DEBUG because corrupt EXIF is common and expected.
                logging.debug('EXIF sub-IFD (0x8769) unreadable: %s', e)
        except Exception as e:
            # Audit P2-20: was a silent "pass" - the whole EXIF block failed.
            logging.debug('EXIF unreadable: %s', e)

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
        Get an importance score (1-9) based on filename patterns.

        Matching is word-boundary aware: a keyword only matches when it
        appears as a whole token, so 'pic' no longer matches 'epic' or
        'picnic', and 'temp' no longer matches 'attempt' or 'Temple'.
        Patterns that carry their own delimiters (e.g. ' (1)', '_copy',
        'new ') are still matched as literal substrings.
        """
        filename_lower = filename.lower()

        # Round 16: a normalised form used for MATCHING ONLY.
        #
        # Two things stop a copy marker from being recognised in an
        # Arabic-locale filename, and both are invisible:
        #   * Arabic-Indic digits -- Windows writes 'نسخة (٢)', and \d does not
        #     match '٢';
        #   * bidirectional marks -- Windows embeds an RTL MARK (U+200F) in
        #     Arabic names, so even the Arabic substring fails to match.
        # Both are normalised away here. The score returned is still computed
        # from the patterns themselves; nothing about the filename is rewritten.
        match_form = _BIDI_MARKS_RE.sub(
            '', self.normalize_arabic_numbers(filename_lower))

        # Default score for an ordinary filename
        max_score = 5

        # Collect matching patterns using word-boundary-aware matching
        found_patterns = []
        for pattern, score in self.filename_importance.items():
            if self._pattern_matches(match_form, pattern):
                found_patterns.append((pattern, score))

        # If patterns matched, the most specific one wins (longest pattern)
        if found_patterns:
            found_patterns.sort(key=lambda x: len(x[0]), reverse=True)
            max_score = found_patterns[0][1]

        # Round 15: a recovery tool's CARVED-FILE name is a machine-generated
        # placeholder, not a user name, so it must not earn a keyword reward.
        #
        # R-Studio writes raw-carved images as
        #     img_<width>x<height>x<bitdepth>_<index>.<ext>
        # Its literal 'img' token matched the photo keyword (7) and then took
        # the clean-name bonus (+1) = 8, which OUTSCORED a genuine, dated user
        # file such as 'Screenshot_<date>_<app>.jpg' (6+1 = 7). On a recovery
        # corpus that inverted 12,645 decisions: the nameless carve was kept
        # and the real, dated file was deleted.
        #
        # The guard matches the SHAPE, not the prefix -- '<word>_<digits>x
        # <digits>x<digits>_<digits>' is unmistakably a carving tool's output
        # and no human names a file that way. Real camera names are untouched:
        # IMG_1234_WA0001.jpg and IMG_0001.jpg do not match this shape.
        #
        # The result is NEUTRAL, not punitive: the name falls back to the
        # ordinary-filename default (5) plus the clean bonus = 6. An empty name
        # neither earns nor loses -- it simply stops beating a real one.
        stem_lower = (match_form.rsplit('.', 1)[0]
                      if '.' in match_form else match_form)
        if re.fullmatch(r'[a-z]+_\d+x\d+x\d+_\d+', stem_lower):
            found_patterns = []
            max_score = 5

        # Penalty for obvious copies/duplicates — cap the score at 3
        #
        # Round 15: the first marker used to be the bare ' (' substring, which
        # matched ANY parenthesised qualifier -- not just numbered copies.
        # 'dsc (Final).jpg' was therefore capped from 8 down to 3 and then
        # bonus'd back to 4, five points below its own weight, and '(USA).pdf'
        # lost to an empty numeric name. The asymmetry was the real defect: the
        # PENALTY was broad (' (' matches every parenthesis) while the bonus
        # EXEMPTION below was narrow (' (1)'..' (9)' only), so a parenthesised
        # word was punished as a copy yet still rewarded as clean.
        #
        # Numbered copies are already covered twice over -- by the explicit
        # ' (1)'..' (9)' entries in the pattern table and by the `numbered`
        # list -- so the broad substring was both redundant and wrong. Only
        # genuine copy wording and genuine numbered copies are penalised now.
        #
        # Round 16: the numbered test now covers ANY number, not just 1-9.
        # The old list stopped at ' (9)', so ' (10)' and above escaped the
        # penalty ENTIRELY and scored as a clean name -- 'photo (10).jpg' was
        # worth 8 while 'photo (9).jpg' was worth 3, which is exactly
        # backwards. On a large recovery the counter grows far past 9, so the
        # user's own corpus contains 'copy (99999999)'. Both regexes run on
        # `match_form`, so Arabic-Indic digits and bidi marks are already gone:
        # 'نسخة (٢٢١٩٧٣٦٠١)' is caught by the parenthesis regex and
        # 'نسخة 10512267' by the Arabic one.
        is_numbered_copy = bool(_NUMBERED_COPY_RE.search(match_form)
                                or _ARABIC_NUMBERED_COPY_RE.search(match_form))
        copy_markers = ['_copy', '- copy', 'duplicate', 'نسخة', 'نسخه']
        if is_numbered_copy or any(self._pattern_matches(match_form, m)
                                   for m in copy_markers):
            max_score = min(max_score, 3)

        # Small bonus (+1) for clean names: no numbered copy suffix.
        #
        # Audit finding P0-8: this used to ALSO skip the bonus when the
        # filename contained 'original'/'camera', on the theory that those
        # patterns "keep their exact score". Combined with their outlier
        # weights (10 and 9, against 7 for every other positive pattern
        # and 8 for dsc/vid/video) that let the filename criterion alone
        # outvote every other criterion, so a tiny file merely NAMED
        # "original.jpg" could beat a 3000x3000 photograph.
        #
        # Both outliers are now 8 -- tied with the dsc/vid/video tier
        # instead of forming a tier of their own -- and the exemption is
        # gone so the bonus applies uniformly. Removing the exemption is
        # NOT optional: lowering the weights while keeping it would have
        # inverted the ordering, because dsc_1234.jpg would score 8+1=9
        # while original.jpg stayed pinned at 8.
        #
        # Round 15: `numbered` / `is_numbered_copy` are computed once above,
        # next to the copy-marker penalty, so the penalty and the bonus
        # exemption can never drift apart again -- that drift was the defect.
        if not is_numbered_copy:
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
        - Round 16: non-ASCII alphabetic patterns ('نسخة', 'نسخه') are ALSO
          matched as substrings. `str.isalpha()` is True for Arabic letters,
          so without the isascii() guard they took the token branch -- and
          the token split is [^a-z]+, which deletes every Arabic character,
          leaving [''] and making an Arabic pattern impossible to ever match.
          Tokenising on [^a-z]+ is correct for Latin keywords and is kept
          exactly as it was for them.
        """
        if pattern.isalpha() and pattern.isascii():
            tokens = re.split(r'[^a-z]+', filename_lower)
            return pattern in tokens
        return pattern in filename_lower
    
    def get_best_date(self, image_path: str, date_priority: str = 'oldest',
                      fallback_mtime: bool = False) -> Tuple[Optional[datetime], str]:
        """
        Get the best date from filename and EXIF, considering priority.
        Returns (date, source) where source is 'filename', 'exif', 'modified'
        or 'none'.

        Round 9: fallback_mtime lets NON-IMAGE files (Word/Excel/PDF/archives)
        take part in the date criterion. They never carry EXIF and usually
        have no date in the name, so without it every office group was a date
        tie and the "oldest copy wins" rule could not express itself. The
        modification time is a real, verifiable timestamp -- and the source is
        reported as 'modified' so a report never pretends it was EXIF data.
        Images keep the default (False): nothing about them changes.
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
            if fallback_mtime:
                try:
                    modified = datetime.fromtimestamp(Path(image_path).stat().st_mtime)
                except OSError:
                    return None, 'none'
                return modified, 'modified'
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
        Returns: -1 if image1 is better, 1 if image2 is better, 0 if equal.
        Decided by DATE ONLY -- filename importance is deliberately not
        consulted here (audit finding P2-14); the selection engine
        scores that as a separate weighted criterion.
        """
        date1, source1 = self.get_best_date(image1_path, date_priority)
        date2, source2 = self.get_best_date(image2_path, date_priority)
        
        # If واحد has no تاريخ, the other فوزs
        if date1 and not date2:
            return -1
        elif date2 and not date1:
            return 1
        elif not date1 and not date2:
            # Audit finding P2-14: this used to fall back to filename
            # importance, so a comparison that claims to be BY DATE
            # silently decided the winner by filename instead. The
            # selection engine already scores filename as its own
            # weighted criterion, so doing it here as well double
            # counted it and polluted the date signal. With no date on
            # either side they are simply equal by date.
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
        
        # Dates are equal. Audit finding P2-14: no filename tiebreak here
        # either, for the same reason as above. Equal dates means equal
        # by date; any filename preference belongs to the filename
        # criterion, not to this one.
        return 0

# Global مثيل
date_extractor = DateExtractor()
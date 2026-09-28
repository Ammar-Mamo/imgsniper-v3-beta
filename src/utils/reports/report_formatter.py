"""
Report formatting and text utilities
"""
# وحدة التقارير - ينشئ ملفات HTML وإحصائيات مفصلة


from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
import imagehash

from ...core.config import config
from ...core.i18n.i18n import i18n
from ...core.file_selector import compute_size_score, compute_resolution_score
from ...utils.helpers.date_extractor import date_extractor
from ...utils.helpers.image_codec import open_image


class ReportFormatter:
    """Handle text formatting and localization for reports."""
    
    def get_text(self, key: str) -> str:
        """Get text from reports section, fallback to common section."""
        try:
            # Try تقريرs قسم أول
            text = i18n.get(f'reports.{key}')
            if text and not text.startswith('[Missing:'):
                return text
        except Exception:
            pass
        
        try:
            # Fجميعback to شائع قسم
            return i18n.get(f'common.{key}')
        except Exception:
            return f"[Missing: {key}]"
    
    def get_localized_fallback(self, english_text: str, arabic_text: str) -> str:
        """Get fallback text based on current language."""
        if i18n.current_language == 'ar':
            return arabic_text
        else:
            return english_text
    
    def _honest_reason(self, key: str, english: str, arabic: str) -> str:
        """Localized report reason with a hard-coded fallback (never [Missing]).

        Audit round 5: report fallbacks used to return "Recovered/backup
        image" for files that were nothing of the sort (#535), or invent
        "shorter filename"/"alphabetical order" stories for byte-identical
        ties (#18/#25). Honest labels instead.
        """
        text = None
        try:
            text = i18n.get(f'reports.{key}')
        except Exception:
            text = None  # deliberate: fall through to the hard-coded text
        if text and not str(text).startswith('[Missing'):
            return text
        return self.get_localized_fallback(english, arabic)
    
    @staticmethod
    def _parse_info_date(info: Dict[str, Any]):
        """Parse the stored 'extracted_date' string back into a datetime."""
        value = info.get('extracted_date')
        if not value or value == 'Unknown':
            return None
        try:
            return datetime.strptime(str(value).split(' (')[0], '%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            return None
    
    def get_selection_reason_prefix(self) -> str:
        """Get selection reason prefix based on current language."""
        try:
            reason_prefix = i18n.get('reports.selection_reason').split(':')[0]
            if reason_prefix.startswith('[Missing'):
                raise ValueError("Missing translation")
            return reason_prefix
        except Exception:
            return self.get_localized_fallback("Selection Reason", "سبب الاختيار")
    
    def get_error_reading_text(self, error_msg: str) -> str:
        """Get error reading file text based on current language."""
        try:
            base_text = i18n.get('reports.error_reading_file')
            if base_text.startswith('[Missing'):
                raise ValueError("Missing translation")
            return f"  ❌ {base_text}: {error_msg}"
        except Exception:
            error_text = self.get_localized_fallback("Error reading file", "خطأ في قراءة الملف")
            return f"  ❌ {error_text}: {error_msg}"
    
    def get_detailed_selection_reason(self, kept_file: str, group_files: List[str], all_files_info: Dict[str, Any]) -> str:
        """Get detailed reason why this file was selected over others in the group."""
        kept_info = all_files_info.get(kept_file, {})
        if 'error' in kept_info:
            return "Selected based on custom priorities"
        
        # جلب deleted ملفات in this group
        deleted_files = [f for f in group_files if f != kept_file]
        if not deleted_files:
            return "Only file in group"
        
        # جلب أولوية أمر and إعدادات - same as صورة_عمليةor
        priority_order = config.get('priorities.order', [1, 2, 3, 4])
        priorities = ['resolution', 'size', 'date', 'filename']
        
        # التأكد من أن priority_order هو قائمة صحيحة
        if not isinstance(priority_order, list) or len(priority_order) != 4:
            priority_order = [1, 2, 3, 4]
        
        # إنشاء أولوية خريطةping and sort by أمر (1=عاليest أولوية)
        priority_mapping = list(zip(priorities, priority_order))
        sorted_priorities = sorted(priority_mapping, key=lambda x: x[1])
        
        # Analyze why this ملف was chosen based on مستخدم's أولوية أمر
        reasons = []
        
        # فحص كل أولوية in the مستخدم's specified أمر
        for priority_type, _ in sorted_priorities:
            if not config.get(f'priorities.{priority_type}_priority', True):
                continue  # Skip disabled priorities
            
            if priority_type == 'resolution':
                reason = self._check_resolution_reason(kept_file, deleted_files, kept_info, all_files_info)
                if reason:
                    reasons.append(reason)
                    break
            elif priority_type == 'size':
                reason = self._check_size_reason(kept_file, deleted_files, kept_info, all_files_info)
                if reason:
                    reasons.append(reason)
                    break
            elif priority_type == 'date':
                reason = self._check_date_reason(kept_file, deleted_files, kept_info, all_files_info)
                if reason:
                    reasons.append(reason)
                    break
            elif priority_type == 'filename':
                reason = self._check_filename_reason(kept_file, deleted_files, kept_info, all_files_info)
                if reason:
                    reasons.append(reason)
                    break
        
        # If we found محدد سببs, return the أول واحد
        reason = reasons[0] if reasons else self._get_fallback_reason(
            kept_file, deleted_files, kept_info, all_files_info
        )
        return self._append_sacrifice_warning(reason, kept_file, group_files)
    
    @staticmethod
    def _fmt_px(px: int) -> str:
        """Human-friendly megapixel formatting for the sacrifice warning."""
        try:
            return f"{px / 1_000_000:.1f}MP"
        except Exception:
            return str(px)
    
    def _append_sacrifice_warning(self, reason: str, kept_file: str,
                                  group_files: List[str]) -> str:
        """Append an explicit warning when a HIGHER-resolution sibling was discarded.

        Dimensions are weighed but never given absolute preference, so an older
        low-resolution "original" can legitimately win -- but the report must
        say so loudly rather than hiding a silent quality downgrade.
        """
        try:
            # Lazy import: avoids any risk of an import cycle at module load.
            from ...core.file_selector import FileSelector
            sacrifice = FileSelector().detect_resolution_sacrifice(kept_file, group_files)
        except Exception:
            return reason
        if not sacrifice:
            return reason

        kept_px, best_px = sacrifice
        kept_txt, best_txt = self._fmt_px(kept_px), self._fmt_px(best_px)
        warn = None
        try:
            warn = i18n.get('safety.resolution_sacrifice_warning').format(kept_txt, best_txt)
        except Exception:
            warn = None
        if not warn or str(warn).startswith('[Missing'):
            warn = self.get_localized_fallback(
                f"Kept a LOWER-resolution file ({kept_txt}) over a higher-resolution one ({best_txt})",
                f"تم الاحتفاظ بملف ذي دقة أقل ({kept_txt}) بدلاً من ملف أعلى دقة ({best_txt})"
            )
        return f"{reason}\n  {warn}"
    
    def _check_resolution_reason(self, kept_file: str, deleted_files: List[str], kept_info: Dict[str, Any], all_files_info: Dict[str, Any]) -> Optional[str]:
        """Check if resolution is the reason for selection."""
        for deleted_file in deleted_files:
            deleted_info = all_files_info.get(deleted_file, {})
            if 'error' not in deleted_info:
                if kept_info['resolution'] > deleted_info['resolution']:
                    # Audit round 5 (#7): above the 10MP cap both files score
                    # exactly 10.0, so the raw pixel gap contributed NOTHING
                    # to the decision and must not be reported as the reason.
                    if compute_resolution_score(kept_info['resolution']) == compute_resolution_score(deleted_info['resolution']):
                        continue
                    return f"higher resolution than {Path(deleted_file).name} ({kept_info['width']}x{kept_info['height']} vs {deleted_info['width']}x{deleted_info['height']})"
        return None
    
    def _check_size_reason(self, kept_file: str, deleted_files: List[str], kept_info: Dict[str, Any], all_files_info: Dict[str, Any]) -> Optional[str]:
        """Check if file size is the reason for selection."""
        for deleted_file in deleted_files:
            deleted_info = all_files_info.get(deleted_file, {})
            if 'error' not in deleted_info:
                if kept_info['size_bytes'] > deleted_info['size_bytes']:
                    # Audit round 5 (#7): at/above the 5MB cap both files
                    # score exactly 10.0 -- the byte gap is score-neutral
                    # and was never the deciding criterion.
                    if compute_size_score(kept_info.get('size_mb', 0.0)) == compute_size_score(deleted_info.get('size_mb', 0.0)):
                        continue
                    resolution_note = ""
                    if kept_info['resolution'] == deleted_info['resolution']:
                        resolution_note = ", same resolution"
                    return f"larger file size than {Path(deleted_file).name} ({kept_info['size_mb']} MB vs {deleted_info['size_mb']} MB{resolution_note})"
        return None
    
    def _check_date_reason(self, kept_file: str, deleted_files: List[str], kept_info: Dict[str, Any], all_files_info: Dict[str, Any]) -> Optional[str]:
        """Check if date is the reason for selection."""
        date_priority = config.get('priorities.date_priority', 'oldest')
        
        for deleted_file in deleted_files:
            deleted_info = all_files_info.get(deleted_file, {})
            if 'error' not in deleted_info:
                kept_date = kept_info.get('extracted_date', 'Unknown')
                deleted_date = deleted_info.get('extracted_date', 'Unknown')
                
                # If kept has تاريخ and deleted doesn't
                if kept_date != 'Unknown' and deleted_date == 'Unknown':
                    context = self._get_context_note(kept_info, deleted_info)
                    return f"has extracted date ({kept_date} vs Unknown{context})"
                
                # If both have تاريخs, compare based on pمرجع
                if kept_date != 'Unknown' and deleted_date != 'Unknown':
                    # Audit round 5 (#14/#239): a filename-derived date is
                    # built as midnight (day-level precision). A same-day
                    # gap against an EXIF timestamp is an artifact of the
                    # missing time, not a real age difference, and must not
                    # be reported as "older/newer extracted date".
                    if (kept_date[:10] == deleted_date[:10]
                            and 'filename' in (kept_info.get('date_source'),
                                               deleted_info.get('date_source'))):
                        continue
                    context = self._get_context_note(kept_info, deleted_info)
                    if date_priority == 'oldest' and kept_date < deleted_date:
                        return f"older extracted date ({kept_date} vs {deleted_date}{context})"
                    elif date_priority == 'newest' and kept_date > deleted_date:
                        return f"newer extracted date ({kept_date} vs {deleted_date}{context})"
        return None
    
    def _check_filename_reason(self, kept_file: str, deleted_files: List[str], kept_info: Dict[str, Any], all_files_info: Dict[str, Any]) -> Optional[str]:
        """Check if filename importance is the reason for selection."""
        for deleted_file in deleted_files:
            deleted_info = all_files_info.get(deleted_file, {})
            if 'error' not in deleted_info:
                if kept_info['filename_importance'] > deleted_info['filename_importance']:
                    context = self._get_context_note(kept_info, deleted_info)
                    return f"better filename importance ({kept_info['filename_importance']}/9 vs {deleted_info['filename_importance']}/9{context})"
        return None
    
    def _get_context_note(self, kept_info: Dict[str, Any], deleted_info: Dict[str, Any]) -> str:
        """Get context note about other equal factors."""
        context_parts = []
        
        # فحص if حجمs are equal
        if kept_info.get('size_bytes') == deleted_info.get('size_bytes'):
            context_parts.append("same size")
        
        # فحص if resolutions are equal
        if kept_info.get('resolution') == deleted_info.get('resolution'):
            context_parts.append("same resolution")
        
        if context_parts:
            return f", {' and '.join(context_parts)}"
        return ""
    
    def calculate_similarity_percentage(self, deleted_file: str, kept_file: str, all_files_info: Optional[Dict[str, Any]] = None, similarity_data: Optional[Dict[str, Dict[str, float]]] = None) -> Optional[float]:
        """Calculate REAL visual similarity percentage between two images. Returns None if no real data available."""
        try:
            # ONLY use حقيقي similarity بيانات if متاح
            if similarity_data and kept_file in similarity_data:
                if deleted_file in similarity_data[kept_file]:
                    return similarity_data[kept_file][deleted_file]
            
            # ONLY محاولة to calculate if ملفات still exist (before deletion)
            if Path(deleted_file).exists() and Path(kept_file).exists():
                # Round 6: decode via the central codec helper so RAW/HEIC
                # files get a real percentage instead of a silent None.
                image_a = open_image(deleted_file)
                image_b = open_image(kept_file)
                if image_a is None or image_b is None:
                    if image_a is not None:
                        image_a.close()
                    if image_b is not None:
                        image_b.close()
                    return None
                try:
                    hash1 = imagehash.phash(image_a)
                    hash2 = imagehash.phash(image_b)
                finally:
                    image_a.close()
                    image_b.close()
                
                # Compute the Hamming distance between the two hashes
                hamming_distance = hash1 - hash2

                # Derive max_distance from the actual hash bit-length so the
                # percentage stays correct even if the phash size changes.
                max_distance = hash1.hash.size
                similarity_percentage = max(0.0, (max_distance - hamming_distance) / max_distance * 100)
                
                return round(similarity_percentage, 1)
            
            # NO ESTIMATED SIMILARITY - return Nواحد if no حقيقي بيانات متاح
            return None
            
        except Exception:
            # NO FALLBACK - return Nواحد if حساب fails
            return None
    
    def get_deletion_reason(self, deleted_file: str, kept_file: str, all_files_info: Dict[str, Any]) -> str:
        """Get specific deletion reason based on priorities and file comparison."""
        deleted_info = all_files_info.get(deleted_file, {})
        kept_info = all_files_info.get(kept_file, {})
        
        if 'error' in deleted_info or 'error' in kept_info:
            # Audit round 5 (#535): an unreadable file says nothing about
            # "recovered/backup" -- report honestly that the reason could
            # not be determined instead of inventing one.
            return self._honest_reason('reason_undetermined',
                                       'Could not determine reason (file info unavailable)',
                                       'تعذر تحديد السبب (معلومات الملف غير متاحة)')
        
        # جلب أولوية أمر and إعدادات
        priority_order = config.get('priorities.order', [1, 2, 3, 4])
        priorities = ['resolution', 'size', 'date', 'filename']
        
        # التأكد من أن priority_order هو قائمة صحيحة
        if not isinstance(priority_order, list) or len(priority_order) != 4:
            priority_order = [1, 2, 3, 4]
        
        # إنشاء أولوية خريطةping and sort by أمر (1=عاليest أولوية)
        priority_mapping = list(zip(priorities, priority_order))
        sorted_priorities = sorted(priority_mapping, key=lambda x: x[1])
        
        # فحص كل أولوية in أمر to determine the سبب
        for priority_type, _ in sorted_priorities:
            if not config.get(f'priorities.{priority_type}_priority', True):
                continue
                
            if priority_type == 'resolution':
                # Score-parity guard: differences above the 10MP cap are
                # score-neutral and were never the deciding criterion.
                if compute_resolution_score(deleted_info['resolution']) != compute_resolution_score(kept_info['resolution']):
                    if deleted_info['resolution'] < kept_info['resolution']:
                        return i18n.get('reports.reason_lower_resolution')
                    elif deleted_info['resolution'] > kept_info['resolution']:
                        return i18n.get('reports.reason_higher_resolution')
                    
            elif priority_type == 'size':
                # Score-parity guard (#7): 7.76MB vs 7.77MB both score 10.0
                # at the 5MB cap -- reporting "Larger file size" there
                # claimed a decision that never happened.
                if compute_size_score(deleted_info.get('size_mb', 0.0)) != compute_size_score(kept_info.get('size_mb', 0.0)):
                    if deleted_info['size_bytes'] < kept_info['size_bytes']:
                        return i18n.get('reports.reason_smaller_size')
                    elif deleted_info['size_bytes'] > kept_info['size_bytes']:
                        return i18n.get('reports.reason_larger_size')
                    
            elif priority_type == 'date':
                date_priority = config.get('priorities.date_priority', 'oldest')
                # Audit round 5 (#1124): use the SAME merged dates (EXIF or
                # filename) the selector and the display block use. The old
                # filename-only comparison could never explain EXIF-driven
                # decisions, so real date differences fell through to the
                # misleading "Recovered/backup" fallback.
                deleted_date = self._parse_info_date(deleted_info)
                kept_date = self._parse_info_date(kept_info)
                
                if deleted_date and kept_date:
                    same_day = deleted_date.date() == kept_date.date()
                    filename_involved = 'filename' in (
                        kept_info.get('date_source'), deleted_info.get('date_source'))
                    # Day-precision guard: a same-day gap involving a
                    # filename date is a midnight artifact, not a decision.
                    if same_day and filename_involved:
                        pass
                    elif date_priority == 'oldest':
                        if deleted_date > kept_date:
                            return i18n.get('reports.reason_newer_date')
                    else:  # جديدest
                        if deleted_date < kept_date:
                            return i18n.get('reports.reason_older_date')
                            
            elif priority_type == 'filename':
                # فحص if ملفاسم indicates recovered/modified ملف
                filename_lower = Path(deleted_file).name.lower()
                if any(keyword in filename_lower for keyword in ['recovered', 'copy', 'duplicate', 'backup', 'temp', 'tmp']):
                    return i18n.get('reports.reason_recovered_image')
                elif deleted_info['filename_importance'] < kept_info['filename_importance']:
                    return i18n.get('reports.reason_modified_name')
        
        # Fجميعback
        # Audit round 5 (#18/#25/#535): the old fallback ALWAYS claimed
        # "Recovered/backup image" -- even for files with no such marker
        # and no measurable difference. Report honestly instead.
        return self._honest_reason('reason_no_difference',
                                   'No decisive difference in weighted criteria (tie broken by scan order)',
                                   'لا فرق حاسم في معايير الوزن (كُسِر التعادل بترتيب الفحص)')
    
    def _get_fallback_reason(self, kept_file: str, deleted_files: List[str], kept_info: Dict[str, Any], all_files_info: Dict[str, Any]) -> str:
        """Get fallback reason when no specific priority-based reason is found."""
        if not deleted_files:
            return "only file in group"
        
        # جلب the أول deleted ملف to compare with
        deleted_file = deleted_files[0]
        deleted_info = all_files_info.get(deleted_file, {})
        
        if 'error' in deleted_info:
            return "other file could not be read"
        
        # Do فعلي comparison to determine the حقيقي سبب
        differences = []
        
        # فحص resolution difference
        if (kept_info.get('resolution', 0) != deleted_info.get('resolution', 0)
                and compute_resolution_score(kept_info.get('resolution', 0)) != compute_resolution_score(deleted_info.get('resolution', 0))):
            if kept_info.get('resolution', 0) > deleted_info.get('resolution', 0):
                differences.append(f"higher resolution ({kept_info['width']}x{kept_info['height']} vs {deleted_info['width']}x{deleted_info['height']})")
            else:
                differences.append(f"lower resolution ({kept_info['width']}x{kept_info['height']} vs {deleted_info['width']}x{deleted_info['height']})")
        
        # فحص حجم difference
        if compute_size_score(kept_info.get('size_mb', 0.0)) != compute_size_score(deleted_info.get('size_mb', 0.0)):
            if kept_info.get('size_bytes', 0) > deleted_info.get('size_bytes', 0):
                differences.append(f"larger file size ({kept_info['size_mb']} MB vs {deleted_info['size_mb']} MB)")
            elif kept_info.get('size_bytes', 0) < deleted_info.get('size_bytes', 0):
                differences.append(f"smaller file size ({kept_info['size_mb']} MB vs {deleted_info['size_mb']} MB)")
        
        # فحص ملفاسم أهمية
        if kept_info.get('filename_importance', 0) > deleted_info.get('filename_importance', 0):
            differences.append(f"better filename importance ({kept_info['filename_importance']}/9 vs {deleted_info['filename_importance']}/9)")
        elif kept_info.get('filename_importance', 0) < deleted_info.get('filename_importance', 0):
            differences.append(f"worse filename importance ({kept_info['filename_importance']}/9 vs {deleted_info['filename_importance']}/9)")
        
        # If we found differences, تقرير the most مهم واحد
        if differences:
            return differences[0]
        
        # If truly identical, check ملفاسم for clues
        # Audit round 5 (#18/#25): "shorter filename" / "alphabetical
        # order" were invented post-hoc stories for exact ties. The
        # selector breaks ties by scan order and no weighted criterion
        # differed -- say exactly that instead of fabricating a reason.
        return self._honest_reason(
            'reason_no_difference',
            'No decisive difference in weighted criteria (tie broken by scan order)',
            'لا فرق حاسم في معايير الوزن (كُسِر التعادل بترتيب الفحص)')
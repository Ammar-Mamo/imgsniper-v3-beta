"""
Report formatting and text utilities
"""
# وحدة التقارير - ينشئ ملفات HTML وإحصائيات مفصلة


from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
import logging
import imagehash

from ...core.config import config, DEFAULT_PRIORITY_ORDER
from ...core.i18n.i18n import i18n
from ...core.file_selector import (
    build_group_scoretable, compute_date_scores,
    compute_resolution_boost_from_pixels, compute_size_score,
    compute_resolution_score,
)
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

    def _score_table_for_group(self, group_files: List[str], all_files_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Round 7: the SAME group scoretable the selector used, rebuilt from
        report info dicts.

        Reports previously reconstructed reasons with ad-hoc per-pair checks
        (first differing criterion wins, no thresholds), which produced
        claims like "Higher resolution" for a 1-pixel gap. Using the exact
        scoring table means a report can only describe differences the
        engine actually scored -- margins and all. Returns None when fewer
        than two readable files remain.
        """
        infos = {}
        for file_path in group_files:
            info = all_files_info.get(file_path, {})
            if 'error' in info:
                continue
            infos[file_path] = info
        if len(infos) < 2:
            return None

        pixels = {f: info.get('resolution', 0) for f, info in infos.items()}
        sizes = {f: info.get('size_bytes', 0) for f, info in infos.items()}
        importances = {f: info.get('filename_importance', 0) for f, info in infos.items()}

        want_oldest = str(config.get('priorities.date_priority', 'oldest')).strip().lower() != 'newest'
        dates = {f: self._parse_info_date(info) for f, info in infos.items()}
        sources = {f: info.get('date_source') for f, info in infos.items()}
        date_scores = compute_date_scores(dates, want_oldest, sources)

        priority_order = config.get('priorities.order', list(DEFAULT_PRIORITY_ORDER))
        if not (isinstance(priority_order, list) and sorted(priority_order) == [1, 2, 3, 4]):
            priority_order = list(DEFAULT_PRIORITY_ORDER)
        boost = compute_resolution_boost_from_pixels(list(pixels.values()))
        enabled = {criterion: bool(config.get(f'priorities.{criterion}_priority', True))
                   for criterion in ('resolution', 'size', 'date', 'filename')}

        return build_group_scoretable(pixels, sizes, importances, date_scores,
                                      priority_order, boost, enabled)

    @staticmethod
    def _active_criteria(table: Dict[str, Any]) -> set:
        """Criteria whose scores actually differ inside this group.

        A criterion where every file scored the same (tie / no data) did not
        decide anything and must never be cited as a reason.
        """
        active = set()
        for criterion in ('resolution', 'size', 'date', 'filename'):
            values = [row['scores'][criterion] for row in table.values()]
            if values and (max(values) - min(values)) > 1e-6:
                active.add(criterion)
        return active

    def _criterion_label(self, criterion: str) -> str:
        """Localized criterion name used inside reason sentences."""
        labels = {
            'resolution': ('criterion_resolution', 'resolution', 'الدقة والأبعاد'),
            'size': ('criterion_size', 'file size', 'الحجم'),
            'filename': ('criterion_filename', 'filename importance', 'أهمية الاسم'),
        }
        key, english, arabic = labels.get(criterion, labels['size'])
        return self._honest_reason(key, english, arabic)

    @staticmethod
    def _name_has_recovery_marker(file_path: str) -> bool:
        """True when the FILE NAME itself carries a recovered/copy marker.

        Round 5 (#535) kept this keyword check deliberately: it is a fact
        about the file name, not an invented story -- unlike the old fallback
        that claimed "Recovered/backup image" for any unexplained tie.
        """
        lower = Path(file_path).name.lower()
        return any(keyword in lower
                   for keyword in ('recovered', 'copy', 'duplicate', 'backup', 'temp', 'tmp'))

    def _describe_criterion(self, criterion: str, better_info: Dict[str, Any],
                            worse_info: Dict[str, Any]):
        """Return (label, better_value, worse_value) for one criterion pair.

        Values are the raw numbers the user sees in the report, so every
        reason sentence can be verified by eye against the file blocks.
        """
        if criterion == 'resolution':
            return (self._criterion_label('resolution'),
                    f"{better_info.get('width')}x{better_info.get('height')}",
                    f"{worse_info.get('width')}x{worse_info.get('height')}")
        if criterion == 'size':
            return (self._criterion_label('size'),
                    f"{better_info.get('size_mb')} MB",
                    f"{worse_info.get('size_mb')} MB")
        if criterion == 'filename':
            return (self._criterion_label('filename'),
                    f"{better_info.get('filename_importance')}/9",
                    f"{worse_info.get('filename_importance')}/9")
        # date: label reflects the actual relationship (older/newer)
        better_date = self._parse_info_date(better_info)
        worse_date = self._parse_info_date(worse_info)
        want_oldest = str(config.get('priorities.date_priority', 'oldest')).strip().lower() != 'newest'
        if better_date and worse_date:
            better_is_older = better_date < worse_date
        else:
            better_is_older = want_oldest
        label = self._honest_reason('reason_older_date', 'Older date', 'تاريخ أقدم') \
            if better_is_older else \
            self._honest_reason('reason_newer_date', 'Newer date', 'تاريخ أحدث')
        return (label,
                str(better_info.get('extracted_date', 'Unknown')),
                str(worse_info.get('extracted_date', 'Unknown')))

    def _criterion_decided_text(self, criterion_label: str, kept_value: str,
                                rival_value: str) -> str:
        """Round 8: the simple deciding sentence -- criterion + values.

        Users found the round-7 wording ("kept file has a higher weighted
        score (+X pts; main advantage: ...)") too complex. The criterion
        together with the two values states the same fact directly, and the
        values keep the sentence unambiguous about WHICH side is better.
        """
        text = self._honest_reason(
            'reason_criterion_decided',
            '{criterion} ({kept} vs {deleted})',
            '{criterion} ({kept} مقابل {deleted})')
        return str(text).format(criterion=criterion_label,
                                kept=kept_value, deleted=rival_value)

    def _criterion_decided_deletion_text(self, criterion_label: str,
                                         kept_value: str,
                                         deleted_value: str) -> str:
        """Round 8 deletion variant: says plainly which file is which."""
        text = self._honest_reason(
            'reason_criterion_decided_deletion',
            '{criterion} (kept: {kept} — this file: {deleted})',
            '{criterion} (المُبقى: {kept} — هذا الملف: {deleted})')
        return str(text).format(criterion=criterion_label,
                                 kept=kept_value, deleted=deleted_value)

    def _tie_reason_text(self, kept_file: str, other_file: str) -> str:
        """Round 8: honest tie labels for the alphabetical tie-break.

        * different filenames -> the alphabetical rule actually decided, so
          the report says so (instead of the old scan-order claim);
        * identical filenames AND identical scores -> a plain "Tie": the
          files are interchangeable, which is what the user needs to know.
        """
        if Path(kept_file).name.lower() == Path(other_file).name.lower():
            return self._honest_reason(
                'reason_tie_full',
                'Tie — identical criteria and filename',
                'تعادل — تطابقت المعايير واسم الملف')
        return self._honest_reason(
            'reason_no_difference',
            'Tie in weighted criteria — kept the alphabetically first filename',
            'تعادل في المعايير الموزونة — أُبقي الاسم الأسبق أبجدياً')

    def _compose_note(self, table: Dict[str, Any], kept_key: str, other_key: str,
                      kept_info: Dict[str, Any], other_info: Dict[str, Any],
                      active: set) -> Optional[str]:
        """One short caveat line naming what the DELETED file was better at.

        Two cases, both truthful:
          * the deleted file genuinely scored higher on an active criterion
            (the kept file simply won on the others) -- say it plainly;
          * every advantage of the deleted file is below the no-decision
            threshold (the #518 case: 736x826 vs 735x826) -- say THAT, so the
            report can no longer imply a reason that never existed.
        """
        kept_row, other_row = table[kept_key], table[other_key]
        best = None
        for criterion in ('resolution', 'size', 'date', 'filename'):
            if criterion not in active:
                continue
            gain = other_row['weighted'][criterion] - kept_row['weighted'][criterion]
            if gain > 0.5 and (best is None or gain > best[0]):
                best = (gain, criterion)
        if best is not None:
            label, other_value, kept_value = self._describe_criterion(
                best[1], other_info, kept_info)
            text = self._honest_reason(
                'reason_note_deleted_higher',
                'note: the deleted file had a higher {criterion} ({deleted} vs {kept})',
                'ملاحظة: الملف المحذوف كان أعلى في {criterion} ({deleted} مقابل {kept})')
            return str(text).format(criterion=label, deleted=other_value, kept=kept_value)

        checks = []
        if other_info.get('resolution', 0) > kept_info.get('resolution', 0):
            checks.append((other_info['resolution'] / max(kept_info.get('resolution', 0) or 1, 1),
                           'resolution',
                           f"{other_info.get('width')}x{other_info.get('height')}",
                           f"{kept_info.get('width')}x{kept_info.get('height')}"))
        if other_info.get('size_bytes', 0) > kept_info.get('size_bytes', 0):
            checks.append((other_info['size_bytes'] / max(kept_info.get('size_bytes', 0) or 1, 1),
                           'size',
                           f"{other_info.get('size_mb')} MB",
                           f"{kept_info.get('size_mb')} MB"))
        if other_info.get('filename_importance', 0) > kept_info.get('filename_importance', 0):
            checks.append((other_info['filename_importance'] / max(kept_info.get('filename_importance', 0) or 1, 1),
                           'filename',
                           f"{other_info.get('filename_importance')}/9",
                           f"{kept_info.get('filename_importance')}/9"))
        checks = [c for c in checks if c[1] not in active]
        if not checks:
            return None
        checks.sort(reverse=True)
        _, criterion, other_value, kept_value = checks[0]
        text = self._honest_reason(
            'reason_note_within_threshold',
            'note: {criterion} differed only within the no-decision threshold ({deleted} vs {kept})',
            'ملاحظة: {criterion} اختلف فقط داخل حد عدم الحسم ({deleted} مقابل {kept})')
        return str(text).format(criterion=self._criterion_label(criterion),
                                deleted=other_value, kept=kept_value)
    
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
    
    def write_run_metadata(self, out, failed_count: int = 0,
                           dry_run: Optional[bool] = None) -> None:
        """Round 18: header lines that make a report self-describing.

        Two facts a forensic reader needs and no report used to carry:

          * WHETHER the run was a dry run. Every report looked identical either
            way, so telling a simulation from a real deletion meant opening
            config/settings.json and hoping it had not changed since. During the
            round-18 investigation this had to be inferred from the absence of
            "Moved to" lines plus an empty recycle bin.
          * WHERE the recycle bin actually was. The bin is resolved from
            Path.cwd(), so it depends on the launch directory; a report that does
            not record it cannot tell you where 40 GB of "deleted" photos went.

        `failed_count` is optional and only printed when non-zero: a run that
        could not move some of its files (a full disk being the real case that
        prompted this round) must say so IN THE REPORT, not only on a console
        line that scrolls away.

        `dry_run` overrides the config value. Round 19 needs it: a RESTORE always
        previews first regardless of safety.dry_run_mode, so printing the global
        setting would claim "DRY-RUN: False" for a restore that changed nothing.

        Takes no new required arguments, so every existing caller keeps working.
        """
        try:
            from ...core.config import config
            from ..helpers.file_utils import get_recycle_bin_root

            if dry_run is None:
                dry_run = bool(config.get('safety.dry_run_mode', False))
            out.write(self.get_localized_fallback(
                'DRY-RUN', 'وضع المحاكاة') + f": {bool(dry_run)}\n")
            out.write(self.get_localized_fallback(
                'Recycle Bin', 'سلة المحذوفات') + f": {get_recycle_bin_root()}\n")
            if failed_count:
                out.write(self.get_localized_fallback(
                    'FILES NOT MOVED (still in their original location)',
                    'ملفات لم تُنقل (ما زالت في مكانها الأصلي)')
                    + f": {failed_count}\n")
        except Exception as e:
            # A report must never fail because a metadata line could not be
            # written; round 13 established that a report problem may not mask a
            # completed operation.
            logging.warning('Report run-metadata line skipped: %s', e)

    def write_path_lines(self, out, file_path: str,
                         moved_map: Optional[Dict[str, str]] = None) -> None:
        """Round 8: write the ORIGINAL path of a file into a report, plus
        the recycle-bin destination it was actually moved to.

        Every report shows the full original path for kept AND deleted
        files (before this round only the corrupted report did, and the
        user had no way to locate a group's files on disk). In real
        (non-dry-run) mode each deleted file also gets a "Moved to" line so
        recovery is a copy-paste away; in dry-run mode nothing was moved,
        so only the original path is written.
        """
        try:
            path_line = i18n.get('reports.image_path').format(file_path)
            if str(path_line).startswith('[Missing'):
                raise ValueError("missing")
        except Exception:
            path_line = f"  📁 Path: {file_path}"
        out.write(path_line + "\n")
        if moved_map and file_path in moved_map:
            try:
                moved_line = i18n.get('reports.moved_to').format(moved_map[file_path])
                if str(moved_line).startswith('[Missing'):
                    raise ValueError("missing")
            except Exception:
                moved_line = f"  📥 Moved to: {moved_map[file_path]}"
            out.write(moved_line + "\n")
    
    def get_detailed_selection_reason(self, kept_file: str, group_files: List[str], all_files_info: Dict[str, Any]) -> str:
        """Honest selection reason computed from the SAME scoretable the
        engine used (round 7).

        The reason is the kept file's largest genuine advantage over its
        CLOSEST rival (the deleted file with the highest weighted total) --
        the old implementation returned the first criterion that happened to
        differ against whichever deleted file came first, with no thresholds,
        so it could pick a 0.01 MB micro-gap over the real deciding factor.
        """
        kept_info = all_files_info.get(kept_file, {})
        if 'error' in kept_info:
            return "Selected based on custom priorities"

        # جلب deleted ملفات in this group
        deleted_files = [f for f in group_files if f != kept_file]
        if not deleted_files:
            return "Only file in group"

        table = self._score_table_for_group(group_files, all_files_info)
        if not table or kept_file not in table:
            return self._honest_reason('reason_undetermined',
                                       'Could not determine reason (file info unavailable)',
                                       'تعذر تحديد السبب (معلومات الملف غير متاحة)')

        rivals = [f for f in deleted_files if f in table]
        if not rivals:
            return self._honest_reason('reason_undetermined',
                                       'Could not determine reason (file info unavailable)',
                                       'تعذر تحديد السبب (معلومات الملف غير متاحة)')

        rival = max(rivals, key=lambda f: table[f]['total'])
        rival_info = all_files_info.get(rival, {})
        kept_row, rival_row = table[kept_file], table[rival]
        margin = kept_row['total'] - rival_row['total']

        active = self._active_criteria(table)
        advantage = None
        best_gain = 0.0
        for criterion in ('resolution', 'size', 'date', 'filename'):
            if criterion not in active:
                continue
            gain = kept_row['weighted'][criterion] - rival_row['weighted'][criterion]
            if gain > best_gain + 1e-9:
                advantage, best_gain = criterion, gain

        if margin > 0.05 and advantage is not None:
            label, kept_value, rival_value = self._describe_criterion(
                advantage, kept_info, rival_info)
            reason = self._criterion_decided_text(label, kept_value, rival_value)
        else:
            reason = self._tie_reason_text(kept_file, rival)

        note = self._compose_note(table, kept_file, rival, kept_info, rival_info, active)
        if note:
            reason = f"{reason}\n  {note}"
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
    
    def get_deletion_reason(self, deleted_file: str, kept_file: str,
                            all_files_info: Dict[str, Any],
                            group_files: List[str] = None) -> str:
        """Honest deletion reason computed from the SAME scoretable the
        engine used (round 7).

        It states what actually decided the outcome and by how much, names
        the genuine advantages the deleted file had, and marks sub-threshold
        differences as such -- instead of the old ambiguous labels
        ("Higher resolution" for a 1-pixel gap, which users read as the
        OPPOSITE of what happened).
        """
        deleted_info = all_files_info.get(deleted_file, {})
        kept_info = all_files_info.get(kept_file, {})

        if 'error' in deleted_info or 'error' in kept_info:
            # Audit round 5 (#535): an unreadable file says nothing about
            # "recovered/backup" -- report honestly that the reason could
            # not be determined instead of inventing one.
            return self._honest_reason('reason_undetermined',
                                       'Could not determine reason (file info unavailable)',
                                       'تعذر تحديد السبب (معلومات الملف غير متاحة)')

        group = list(group_files) if group_files else [kept_file, deleted_file]
        if kept_file not in group:
            group.append(kept_file)
        if deleted_file not in group:
            group.append(deleted_file)

        table = self._score_table_for_group(group, all_files_info)
        if not table or kept_file not in table or deleted_file not in table:
            return self._tie_reason_text(kept_file, deleted_file)

        kept_row, deleted_row = table[kept_file], table[deleted_file]
        margin = kept_row['total'] - deleted_row['total']
        active = self._active_criteria(table)

        advantage = None
        best_gain = 0.0
        for criterion in ('resolution', 'size', 'date', 'filename'):
            if criterion not in active:
                continue
            gain = kept_row['weighted'][criterion] - deleted_row['weighted'][criterion]
            if gain > best_gain + 1e-9:
                advantage, best_gain = criterion, gain

        if margin > 0.05 and advantage is not None:
            label, kept_value, deleted_value = self._describe_criterion(
                advantage, kept_info, deleted_info)
            main = self._criterion_decided_deletion_text(
                label, kept_value, deleted_value)
        elif self._name_has_recovery_marker(deleted_file):
            # Round 5 (#535) kept behaviour: the recovered/copy/bak marker is
            # a fact about the file name. Only used when nothing scored.
            main = self._honest_reason('reason_recovered_image',
                                       'Recovered/backup image',
                                       'صورة مستردة/نسخة احتياطية')
        else:
            # Audit round 5 (#18/#25): the old fallback ALWAYS claimed
            # "Recovered/backup image" -- even for files with no such marker
            # and no measurable difference. Report honestly instead.
            main = self._tie_reason_text(kept_file, deleted_file)

        note = self._compose_note(table, kept_file, deleted_file,
                                  kept_info, deleted_info, active)
        return f"{main}\n  {note}" if note else main
    

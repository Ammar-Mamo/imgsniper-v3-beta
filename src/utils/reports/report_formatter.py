"""
Report formatting and text utilities
"""
# وحدة التقارير - ينشئ ملفات HTML وإحصائيات مفصلة


from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
import logging
import imagehash

from ...core import name_provenance
from ...core.config import config, DEFAULT_PRIORITY_ORDER
from ...core.i18n.i18n import i18n
from ...core.file_selector import (
    build_group_scoretable, compute_date_scores,
    compute_resolution_boost_from_pixels, compute_size_score,
    compute_resolution_score, is_day_level_date, date_criterion_decides,
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

    @staticmethod
    def _provenance_of(file_path: str) -> int:
        """Name-provenance class of one file (the Round 20 hard gate).

        The selection engine ranks a group by (-provenance, -total, name), so a
        report that ignored the class would describe a decision the engine never
        made -- exactly the defect this round closes. Any failure falls back to
        the neutral class, which can only ever UNDER-state an advantage, never
        invent one.
        """
        try:
            return name_provenance.provenance_of(Path(file_path).name)
        except Exception:
            return name_provenance.CLASS_NEUTRAL

    @staticmethod
    def _gate_tier_of(file_path: str) -> int:
        """The tier the engine's hard gate compared (see name_provenance).

        Ranking and deciding use the TIER; only the WORDING uses the full class,
        so a report can call a name "original-looking" without implying that the
        label alone is what kept it.
        """
        try:
            return name_provenance.gate_tier_of(Path(file_path).name)
        except Exception:
            return name_provenance.CLASS_NEUTRAL

    @staticmethod
    def _effective_tier_of(file_path: str, date_decides: bool) -> int:
        """The tier the engine ACTUALLY ranked by (round 21).

        The gate is conditional now: it may veto only when the date evidence is
        weak (no contest, or a seconds/minutes/hours gap). A report that kept
        comparing the unconditional tier would describe a veto the engine never
        applied -- the exact class of bug this whole round exists to remove.
        """
        try:
            return name_provenance.effective_gate_tier(
                name_provenance.provenance_of(Path(file_path).name), date_decides)
        except Exception:
            return name_provenance.CLASS_NEUTRAL

    def _date_decides_for_group(self, group_files: List[str],
                                all_files_info: Dict[str, Any]) -> bool:
        """Whether the date gap in this group overrules the name-originality gate.

        Computed from the SAME info dicts the scoretable is built from, through
        the SAME helper the engine calls, so a report can never claim a different
        winner than the engine picked.
        """
        dates, sources = {}, {}
        for file_path in group_files:
            info = all_files_info.get(file_path, {})
            if not info or 'error' in info:
                continue
            dates[file_path] = self._parse_info_date(info)
            sources[file_path] = info.get('date_source')
        try:
            return date_criterion_decides(dates, sources)
        except Exception:
            return False

    def _date_gap_note(self, kept_info: Dict[str, Any], other_info: Dict[str, Any],
                       deletion: bool = False) -> Optional[str]:
        """The round-21 review flag: the gate won although the dates differed.

        The user asked to be able to RELY on this tool, which means the borderline
        decisions must be visible instead of buried. When the name gate decides
        while the two dates genuinely differ -- but by less than the configured
        threshold -- the report now says so plainly and names the gap, so a
        decision that a human might want to overrule can be found by reading the
        report rather than by re-auditing 65 000 groups afterwards.
        """
        kept_date = self._parse_info_date(kept_info)
        other_date = self._parse_info_date(other_info)
        if not kept_date or not other_date or kept_date == other_date:
            return None
        hours = abs((kept_date - other_date).total_seconds()) / 3600.0
        threshold = config.get('priorities.name_gate_date_gap_hours', 24)
        try:
            threshold = float(threshold)
        except (TypeError, ValueError):
            threshold = 24.0
        if hours < 1.0:
            span_text = self._honest_reason(
                'gap_minutes', 'less than an hour', 'أقل من ساعة')
        elif hours < 48.0:
            span_text = self._honest_reason(
                'gap_hours', '{0:.0f} hours', '{0:.0f} ساعة').format(hours)
        else:
            span_text = self._honest_reason(
                'gap_days', '{0:.0f} days', '{0:.0f} يوم').format(hours / 24.0)
        text = self._honest_reason(
            'reason_note_gate_over_older_date',
            'review: the dates differ by {gap}, below the {threshold}-hour '
            'threshold at which the date overrules name originality, so the '
            'cleaner name decided ({deleted} vs {kept})',
            'مراجعة: التاريخان يفترقان بـ {gap}، وهو دون حد {threshold} ساعة '
            'الذي يجعل التاريخ يتجاوز أصالة الاسم، لذلك حسم الاسم الأنظف '
            '({deleted} مقابل {kept})')
        return str(text).format(gap=span_text, threshold=int(threshold),
                                deleted=str(other_info.get('extracted_date', 'Unknown')),
                                kept=str(kept_info.get('extracted_date', 'Unknown')))

    def _provenance_reason(self, kept_file: str, other_file: str,
                           deletion: bool = False) -> str:
        """The reason line for a decision the name-provenance gate made."""
        kept_label = name_provenance.class_label(self._provenance_of(kept_file))
        other_label = name_provenance.class_label(self._provenance_of(other_file))
        if deletion:
            text = self._honest_reason(
                'reason_name_provenance_deletion',
                'name originality (kept: {kept} — this file: {deleted})',
                'أصالة الاسم (المُبقى: {kept} — هذا الملف: {deleted})')
            return str(text).format(kept=kept_label, deleted=other_label)
        text = self._honest_reason(
            'reason_name_provenance',
            'name originality ({kept} beats {deleted})',
            'أصالة الاسم ({kept} يتفوق على {deleted})')
        return str(text).format(kept=kept_label, deleted=other_label)

    def _provenance_note(self, kept_file: str, other_file: str) -> Optional[str]:
        """A supporting note about the name classes, when they differ.

        Round 21: when the weighted criteria already decided the group, the name
        gate was never needed -- but the user still deserves to see that one side
        carried a copy/recovery marker, because that is evidence about where each
        file came from. It is printed as a NOTE under the real reason instead of
        masquerading as the reason itself.
        """
        if self._provenance_of(kept_file) == self._provenance_of(other_file):
            return None
        text = self._honest_reason(
            'reason_note_name_class',
            'note: name originality also favoured the kept file ({kept} vs {deleted})',
            'ملاحظة: أصالة الاسم كانت أيضًا لصالح الملف المُبقى ({kept} مقابل {deleted})')
        return str(text).format(
            kept=name_provenance.class_label(self._provenance_of(kept_file)),
            deleted=name_provenance.class_label(self._provenance_of(other_file)))

    def _date_precision_note(self, table: Dict[str, Any], kept_key: str,
                             other_key: str, kept_info: Dict[str, Any],
                             other_info: Dict[str, Any],
                             active: set) -> Optional[str]:
        """Explain a date criterion that the day-level gate neutralised.

        This is the note whose absence made the reports unreadable: a group
        printed two DIFFERENT dates side by side and then named some other
        criterion as the reason, with no word about the date. The engine really
        did score the date as a tie -- a filename date with no time in it is
        only precise to the day, so two timestamps on the same day cannot be
        ordered -- and now the report says exactly that instead of leaving the
        reader to guess.
        """
        if 'date' in active:
            return None                       # the date really competed
        kept_date = self._parse_info_date(kept_info)
        other_date = self._parse_info_date(other_info)
        if not kept_date or not other_date or kept_date == other_date:
            return None
        if not (is_day_level_date(kept_date, kept_info.get('date_source'))
                or is_day_level_date(other_date, other_info.get('date_source'))):
            return None
        text = self._honest_reason(
            'reason_note_date_day_level',
            'note: the dates differ, but a filename date in this group has '
            'day-level precision (no time written in the name), so the date '
            'criterion could not decide ({deleted} vs {kept})',
            'ملاحظة: التاريخان مختلفان، لكن تاريخ اسم الملف في هذه المجموعة '
            'دقيقته اليوم فقط (لا يوجد وقت مكتوب في الاسم)، لذلك لم يتمكن '
            'معيار التاريخ من الحسم ({deleted} مقابل {kept})')
        return str(text).format(
            deleted=str(other_info.get('extracted_date', 'Unknown')),
            kept=str(kept_info.get('extracted_date', 'Unknown')))

    def _supporting_criteria_note(self, table: Dict[str, Any], kept_key: str,
                                  other_key: str, kept_info: Dict[str, Any],
                                  other_info: Dict[str, Any], active: set) -> Optional[str]:
        """List the weighted criteria that ALSO favoured the kept file.

        Round 20: the name-originality gate decides BEFORE the weighted sum, so
        without this note a group would read "name originality" and hide the fact
        that the DATE agreed -- which is precisely the confusion the user raised
        ("a photo chosen because of the date in its name must not be reported as
        chosen for the importance of the name"). Naming the gate is correct, but
        it must not swallow the other evidence: when the date, resolution or size
        point the same way, the report now says so explicitly, with the same
        values and source labels used everywhere else.
        """
        kept_row, other_row = table.get(kept_key), table.get(other_key)
        if not kept_row or not other_row:
            return None
        parts = []
        for criterion in ('date', 'resolution', 'size', 'filename'):
            if criterion not in active:
                continue
            if kept_row['weighted'][criterion] - other_row['weighted'][criterion] <= 1e-9:
                continue
            label, kept_value, other_value = self._describe_criterion(
                criterion, kept_info, other_info)
            parts.append(f"{label}: {kept_value} vs {other_value}")
        if not parts:
            return None
        text = self._honest_reason(
            'reason_note_also_favoured',
            'the weighted criteria agree with this: {}',
            'المعايير الموزونة تؤيد هذا الاختيار: {}')
        return str(text).format(' | '.join(parts))

    @staticmethod
    def _join_notes(reason: str, notes) -> str:
        """Append every non-empty caveat line under the reason sentence."""
        seen = []
        for note in notes:
            if note and note not in seen:
                seen.append(note)
        if not seen:
            return reason
        return reason + ''.join(f"\n  {note}" for note in seen)

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
        # Round 20: name WHERE each date came from. The user's exact complaint
        # was that a photo whose date lives in its own NAME was reported as kept
        # for "filename importance" -- so when the date really does decide, the
        # sentence now proves it was the date, and shows that the winning
        # timestamp was read from the filename (or from EXIF) instead of leaving
        # the reader to reconstruct it from the file blocks.
        return (label,
                self._date_with_source(better_info),
                self._date_with_source(worse_info))

    def _date_with_source(self, info: Dict[str, Any]) -> str:
        """'2022-07-06 14:53:47 [from filename]' -- a date plus its origin."""
        value = str(info.get('extracted_date', 'Unknown'))
        source = str(info.get('date_source') or '').strip().lower()
        key, english, arabic = {
            'filename': ('date_source_filename', 'from filename', 'من اسم الملف'),
            'exif': ('date_source_exif', 'from EXIF', 'من EXIF'),
            'modified': ('date_source_modified', 'file modified', 'وقت تعديل الملف'),
        }.get(source, (None, None, None))
        if key is None or value == 'Unknown':
            return value
        return f"{value} [{self._honest_reason(key, english, arabic)}]"

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

        # Round 20: the runner-up under the SAME ranking the engine used --
        # (-provenance, -total, name). Choosing the rival by total alone would
        # name a competitor the provenance gate had already eliminated, and the
        # reason would then describe a contest that never happened.
        # Round 21: the gate is conditional, so the report must know whether the
        # date was strong enough to overrule it -- otherwise it would describe a
        # veto the engine never applied.
        date_decides = self._date_decides_for_group(group_files, all_files_info)
        tiers = {f: self._effective_tier_of(f, date_decides) for f in group_files}
        neutral = name_provenance.CLASS_NEUTRAL
        rival = min(rivals, key=lambda f: (-tiers.get(f, neutral),
                                           -table[f]['total'],
                                           Path(f).name.lower()))
        rival_info = all_files_info.get(rival, {})
        kept_row, rival_row = table[kept_file], table[rival]
        margin = kept_row['total'] - rival_row['total']

        active = self._active_criteria(table)

        # Round 21: name the criterion that ACTUALLY made the difference. When the
        # weighted sum already favoured the kept file the gate was never needed, so
        # the honest primary reason is the criterion that won -- usually the date,
        # the user's priority #1 -- and the name class becomes a supporting note.
        # Claiming "name originality" there would repeat the very defect this whole
        # round exists to remove: a date-based choice reported as a name-based one.
        tier_gap = tiers.get(kept_file, neutral) > tiers.get(rival, neutral)
        gate_fired = tier_gap and margin <= 0.05
        if gate_fired:
            # The name-provenance gate decided: a derived name (recovered /
            # copy / a "(N)" counter / a machine carve) never survives against a
            # more original one, whatever the weighted scores say.
            reason = self._provenance_reason(kept_file, rival)
        else:
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

        notes = [self._compose_note(table, kept_file, rival, kept_info,
                                    rival_info, active),
                 self._date_precision_note(table, kept_file, rival, kept_info,
                                            rival_info, active)]
        if tier_gap:
            # The name classes differ, so the user always gets to see that -- as
            # the REASON when the gate decided, as a NOTE when it did not.
            notes.append(self._provenance_note(kept_file, rival))
        if gate_fired:
            # The gate outranks the weighted sum, but it must not HIDE it: when
            # the date or the resolution point the same way the user has to see
            # that too (their exact complaint was a date-based choice being
            # reported as a name-based one).
            notes.append(self._supporting_criteria_note(
                table, kept_file, rival, kept_info, rival_info, active))
            # Round 21: flag the borderline case -- the gate won even though the
            # dates genuinely differed, just by less than the threshold.
            notes.append(self._date_gap_note(kept_info, rival_info))
        reason = self._join_notes(reason, notes)
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

        # Round 21: the gate is conditional on the strength of the date evidence,
        # so this must use the SAME effective tier the engine ranked by.
        date_decides = self._date_decides_for_group(group, all_files_info)
        # Round 21: the gate is the REASON only when it is what made the
        # difference. If the weighted sum already favoured the kept file, the
        # criterion that won is the honest headline and the name class is a note.
        tier_gap = (self._effective_tier_of(kept_file, date_decides)
                    > self._effective_tier_of(deleted_file, date_decides))
        gate_fired = tier_gap and margin <= 0.05
        if gate_fired:
            # Round 20: the name-provenance gate decided. This is the honest
            # label for the case that used to read "Older date" while keeping a
            # recovered carve -- the date may well have favoured the deleted
            # file, but a derived name cannot survive against a more original
            # one, and _compose_note below still names the advantages it had.
            main = self._provenance_reason(kept_file, deleted_file, deletion=True)
        else:
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
                # Round 5 (#535) kept behaviour: the recovered/copy/bak marker
                # is a fact about the file name. Only used when nothing scored.
                main = self._honest_reason('reason_recovered_image',
                                           'Recovered/backup image',
                                           'صورة مستردة/نسخة احتياطية')
            else:
                # Audit round 5 (#18/#25): the old fallback ALWAYS claimed
                # "Recovered/backup image" -- even for files with no such marker
                # and no measurable difference. Report honestly instead.
                main = self._tie_reason_text(kept_file, deleted_file)

        notes = [self._compose_note(table, kept_file, deleted_file,
                                    kept_info, deleted_info, active),
                 self._date_precision_note(table, kept_file, deleted_file,
                                           kept_info, deleted_info, active)]
        if tier_gap:
            # Same rule as the selection reason: the name classes differ, so the
            # user sees it -- as the REASON when the gate decided, as a NOTE when
            # a weighted criterion already had.
            notes.append(self._provenance_note(kept_file, deleted_file))
        if gate_fired:
            notes.append(self._supporting_criteria_note(
                table, kept_file, deleted_file, kept_info, deleted_info, active))
            notes.append(self._date_gap_note(kept_info, deleted_info))
        return self._join_notes(main, notes)
    

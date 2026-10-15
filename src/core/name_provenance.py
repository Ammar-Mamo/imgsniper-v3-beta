"""
Name provenance -- is this filename an ORIGINAL, or a derived copy?
أصالة اسم الملف: هل الاسم أصلي أم نسخة مشتقة؟

Why this module exists (Round 20)
---------------------------------
An EXIF date alone does NOT prove a file is the original. A recovery tool
carves a JPEG straight off the disk and the carve keeps a perfect EXIF
timestamp -- often an OLDER one than the copy that survived, because the
surviving file was re-saved by WhatsApp, a browser or an editor. Judging such a
group on the date alone keeps the machine-generated carve and deletes the
user's own named file. Measured on the shipped reports: 174 similar-image
groups and 172 duplicate groups kept a penalised name (recovered / copy /
a "(N)" counter), and in 38 of those a CLEAN-named file was deleted instead.

So the NAME is evidence about WHERE a file came from, which is stronger than
any score. It is therefore applied as a HARD GATE, exactly as the video engine
already does it in video_file_selector.py:

  * an original-looking name beats a copy-suffixed or recovered one, whatever
    the dates, sizes or resolutions say;
  * BETWEEN files of the same class the configured weighted criteria decide,
    in the user's own priority order -- so among equally original names the
    OLDER date still wins.

That satisfies both halves of the rule at once, and it is why a "recovered"
file with the oldest EXIF date in the group can no longer be reported as
"kept because of its older date".

Deliberately NOT merged with video_file_selector
------------------------------------------------
The two engines stay separate for now (the user asked for that explicitly).
This module serves FileSelector -- images, office documents, archives and
other files -- and reuses the SAME taxonomy and marker lists as the video
selector so the two sectors reach CONSISTENT verdicts on the same kind of
name. Unifying the engines themselves is a later, separate step.

Deliberately NOT touching date_extractor.filename_importance
------------------------------------------------------------
The 1-9 importance scale stays exactly as it is: it remains a weighted
criterion (a camera-prefixed name is worth more than a bare one), while the
class below is a gate. Changing the importance map would silently alter every
existing image decision twice over.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..utils.helpers.date_extractor import date_extractor
from .i18n.i18n import i18n

# ---------------------------------------------------------------------------
# The provenance classes. Higher is more credible. Compared FIRST, before any
# weighted score, so a derived name can never win on a metric.
# ---------------------------------------------------------------------------
CLASS_RECOVERED = 0
CLASS_COPY = 1
CLASS_WEAK = 2
CLASS_NEUTRAL = 3
CLASS_ORIGINAL = 4

# (i18n key, English fallback, Arabic fallback) -- a report can never print
# "[Missing: ...]", following the _honest_reason() convention of round 5.
CLASS_LABELS = {
    CLASS_ORIGINAL: ('name_provenance.class_original',
                     'original-looking name', 'اسم يبدو أصليًا'),
    CLASS_NEUTRAL: ('name_provenance.class_neutral',
                    'neutral name (no copy or recovery marker)',
                    'اسم محايد (بلا علامة نسخ أو استرداد)'),
    CLASS_WEAK: ('name_provenance.class_weak',
                 'weak marker in the name (backup / temp / edited)',
                 'علامة ضعيفة في الاسم (نسخة احتياطية / مؤقت / معدّل)'),
    CLASS_COPY: ('name_provenance.class_copy',
                 'copy-suffixed or copy-named',
                 'اسم بلاحقة نسخ أو بكلمة نسخ'),
    CLASS_RECOVERED: ('name_provenance.class_recovered',
                      'recovery-style name', 'اسم بأسلوب الاسترداد'),
}

# ---------------------------------------------------------------------------
# Name markers. Matched as WORDS (token equality or token prefix), never as raw
# substrings, so "David.jpg" is not a "vid" camera file and "attempt.jpg" is not
# a "temp" file. Detection reads the FILENAME TEXT only -- it never asks the
# operating system for a locale, so the behaviour is identical everywhere.
# ---------------------------------------------------------------------------
RECOVERY_MARKERS = ('recovered', 'recovery', 'recover', 'restored', 'restore',
                    'undeleted', 'undelete', 'salvaged', 'salvage',
                    'مستردة', 'مسترد', 'مستعادة', 'مستعاد', 'استرداد', 'استعادة')
COPY_MARKERS = ('copy', 'clone', 'duplicate',
                'نسخة', 'نسخ', 'مكررة', 'مكرر', 'تكرار')
WEAK_MARKERS = ('backup', 'bak', 'temp', 'tmp', 'edited', 'modified', 'new',
                'converted', 'convert', 'exported', 'export',
                'احتياطية', 'احتياطي', 'مؤقت', 'معدّل', 'معدل')
ORIGINAL_MARKERS = ('original', 'orig', 'camera', 'video', 'vid', 'img',
                    'image', 'dsc', 'dcim', 'photo', 'pic', 'clip', 'rec',
                    'screenshot', 'snapchat', 'whatsapp')

# "file (1).jpg" / "file (15).jpg": a parenthesised number at the END of the
# stem is a copy counter -- any number of digits, not only 1-9, because on a
# large recovery the counter grows far past 9 ("copy (99999999)").
COPY_SUFFIX_RE = re.compile(r'\(\s*(\d+)\s*\)\s*$')
# "Movie (2018).jpg" is a YEAR, not a copy counter, and must not be penalised.
YEAR_SUFFIX_RE = re.compile(r'\(\s*(?:19|20)\d{2}\s*\)\s*$')
# Arabic "نسخة 10512267" -- the unparenthesised form Windows also writes.
ARABIC_COPY_RE = re.compile(r'نسخ[هة]\s*\d+')

# Tokens are runs of digits / latin letters / Arabic letters. Everything else
# (spaces, dashes, underscores, dots, brackets) separates them.
_TOKEN_RE = re.compile(r'[^0-9a-z\u0600-\u06ff]+')

# A recovery tool's CARVED-FILE name is machine-generated, not a user name:
# R-Studio writes 'img_<width>x<height>x<bitdepth>_<index>.jpg'. Its literal
# 'img' token must NOT earn the original-looking class, or a nameless carve
# outranks the real dated photo it was carved beside. The guard matches the
# SHAPE, not the prefix, so genuine camera names (IMG_1234_WA0001.jpg,
# IMG_0001.jpg) are untouched.
_CARVED_SHAPE_RE = re.compile(r'[a-z]+_\d+x\d+x\d+_\d+')


def _text(key: str, english: str, arabic: str, *args) -> str:
    """Localized text with a hard-coded fallback (never "[Missing: ...]")."""
    value = None
    try:
        value = i18n.get(key)
    except Exception:                                  # pragma: no cover
        value = None
    if not value or str(value).startswith('[Missing'):
        value = arabic if i18n.current_language == 'ar' else english
    value = str(value)
    if args:
        try:
            return value.format(*args)
        except (IndexError, KeyError, ValueError):     # pragma: no cover
            return value
    return value


def _normalized_stem(filename: str) -> str:
    """Stem, lower-cased, Arabic-Indic digits and bidi marks normalised away.

    Two things hide a copy marker in an Arabic-locale filename and both are
    invisible: Windows writes 'نسخة (٢)' with Arabic-Indic digits that \\d does
    not match, and it embeds a RIGHT-TO-LEFT MARK (U+200F) that breaks even the
    Arabic substring. Both are removed for MATCHING ONLY -- nothing about the
    filename is ever rewritten.
    """
    from ..utils.helpers.date_extractor import _BIDI_MARKS_RE
    stem = Path(str(filename or '')).stem
    return _BIDI_MARKS_RE.sub('', date_extractor.normalize_arabic_numbers(stem.lower()))


def _tokens(stem: str) -> List[str]:
    """Word tokens of a normalised stem."""
    return [token for token in _TOKEN_RE.split(stem) if token]


def _match_marker(tokens: List[str], markers) -> Tuple[Optional[str], Optional[str]]:
    """First (token, marker) where the token IS the marker -- whole words only.

    Round 20: this deliberately does NOT use token.startswith(marker). A prefix
    test downgrades ordinary names that merely begin with a marker, which is the
    exact defect round 15 removed from the importance scale: 'Temple_run.jpg'
    read as a "temp" file and 'picturesque.jpg' as a "pic" camera file. The
    tokenizer already splits on every non-alphanumeric character, so a real
    marker usually arrives as its own token -- 'Recovered_jpg_file(1082).jpg'
    yields ['recovered', 'jpg', 'file', '1082'] and matches exactly.

    One prefix case is still accepted, because it IS the marker: a counter glued
    straight onto the word, 'نسخة٣' (normalised to 'نسخة3') or 'copy2'. The
    remainder must be ALL DIGITS, which is what keeps 'Temple' and 'picturesque'
    out -- their remainders are letters.
    """
    for token in tokens:
        for marker in markers:
            if token == marker:
                return token, marker
            if token.startswith(marker) and token[len(marker):].isdigit():
                return token, marker
    return None, None


def analyze_name(filename: str) -> Dict[str, Any]:
    """Explainable provenance analysis of ONE filename (no file access at all).

    Returns the class, its localized label and the human-readable reasons behind
    it. These are HEURISTICS, not truth -- a name can lie, which is exactly why
    the reasons are recorded: a report shows why a file was preferred and the
    user can overrule it.

    Numbers are never penalised as such: "20180817.jpg", "Episode 2.jpg" and
    "Camera 02.jpg" carry no copy marker. Only a parenthesised counter at the
    END of the stem counts as one, and a parenthesised YEAR does not.
    """
    name = Path(str(filename or '')).name
    stem = _normalized_stem(filename)
    tokens = _tokens(stem)
    reasons: List[str] = []
    provenance = CLASS_NEUTRAL
    copy_suffix = None

    # 1) A copy counter in parentheses at the end of the stem.
    match = COPY_SUFFIX_RE.search(stem)
    if match:
        number = match.group(1)
        if YEAR_SUFFIX_RE.search(stem):
            reasons.append(_text('name_provenance.year_not_copy',
                                 '"{}" is a year in parentheses, not a copy number',
                                 '"{}" سنة بين قوسين وليست رقم نسخة', f'({number})'))
        else:
            copy_suffix = f'({number})'
            provenance = min(provenance, CLASS_COPY)
            reasons.append(_text('name_provenance.copy_suffix',
                                 'copy suffix "{}" at the end of the name',
                                 'لاحقة نسخ "{}" في آخر الاسم', copy_suffix))

    # 2) The unparenthesised Arabic copy form.
    if ARABIC_COPY_RE.search(stem):
        provenance = min(provenance, CLASS_COPY)
        reasons.append(_text('name_provenance.arabic_copy',
                             'Arabic copy wording in the name',
                             'صيغة نسخ عربية في الاسم'))

    # 3) Word markers, worst class first, so "Recovered Copy" stays RECOVERED.
    token, marker = _match_marker(tokens, RECOVERY_MARKERS)
    if marker:
        provenance = min(provenance, CLASS_RECOVERED)
        reasons.append(_text('name_provenance.recovery_marker',
                             'recovery marker "{}" in the name',
                             'علامة استرداد "{}" في الاسم', marker))

    token, marker = _match_marker(tokens, COPY_MARKERS)
    if marker:
        provenance = min(provenance, CLASS_COPY)
        reasons.append(_text('name_provenance.copy_marker',
                             'copy marker "{}" in the name',
                             'علامة نسخ "{}" في الاسم', marker))

    token, marker = _match_marker(tokens, WEAK_MARKERS)
    if marker:
        provenance = min(provenance, CLASS_WEAK)
        reasons.append(_text('name_provenance.weak_marker',
                             'weak marker "{}" in the name (backup / temp / edited)',
                             'علامة ضعيفة "{}" في الاسم (احتياطية / مؤقت / معدّل)', marker))

    # 4) The original-looking class is an UPGRADE, and only for a name that was
    #    not already downgraded -- a "recovered_img_0001.jpg" stays recovered.
    carved = bool(_CARVED_SHAPE_RE.fullmatch(stem))
    if carved:
        # Round 20: a carved name is RECOVERY output, full stop. It is not merely
        # "no information" -- it is a file the user never named, written by a
        # tool that pulled the bytes off the disk. Round 15 already refused to
        # give it the camera-keyword REWARD (importance 8 -> 6); the gate goes
        # further and refuses to let it SURVIVE against anything a user named,
        # including a numbered copy. Without this, 'img_1280x853x24_001092.jpg'
        # scored neutral and beat 'IMG-20240824-WA0015(1).jpg', whose "(1)" had
        # correctly marked it a copy -- which is exactly backwards: the WhatsApp
        # name still carries a real capture date, the carve carries nothing.
        provenance = min(provenance, CLASS_RECOVERED)
        reasons.append(_text('name_provenance.carved_shape',
                             'machine-generated carved-file name shape '
                             '(a recovery tool wrote it, not a user)',
                             'شكل اسم ملف مستخرج آليًا (كتبه برنامج استرداد لا مستخدم)'))
    elif provenance == CLASS_NEUTRAL:
        token, marker = _match_marker(tokens, ORIGINAL_MARKERS)
        if marker:
            provenance = CLASS_ORIGINAL
            reasons.append(_text('name_provenance.original_marker',
                                 'camera/original marker "{}" in the name',
                                 'علامة كاميرا/أصل "{}" في الاسم', marker))

    if provenance >= CLASS_NEUTRAL:
        reasons.append(_text('name_provenance.clean_name',
                             'no copy or recovery marker - the name looks original',
                             'لا علامة نسخ أو استرداد - الاسم يبدو أصليًا'))

    key, english, arabic = CLASS_LABELS[provenance]
    return {
        'name': name,
        'stem': stem,
        'provenance': provenance,
        'provenance_label': _text(key, english, arabic),
        'copy_suffix': copy_suffix,
        'carved': carved,
        'reasons': reasons,
    }


def provenance_of(filename: str) -> int:
    """Just the class -- the cheap call the selection engine needs per file."""
    return analyze_name(filename)['provenance']

def gate_tier(provenance: int) -> int:
    """The tier the HARD GATE compares.

    CLASS_ORIGINAL and CLASS_NEUTRAL deliberately share ONE tier. The gate's job
    is to stop a DERIVED file (recovered / copy / a "(N)" counter / backup) from
    surviving against the user's own file -- it is NOT a licence to prefer one
    clean name over another.

    That distinction matters on a real corpus. A bare date name such as
    '٢٠١٦٠٩١٥_١٨٤٤٠٦.jpg' is a Samsung camera default and every bit as original
    as 'IMG_20181117_142355.jpg'; letting the 'img' token outrank it absolutely
    would delete the OLDER of two originals, which is exactly the loss this round
    exists to prevent. Between two clean names the weighted criteria decide --
    the DATE first, as the user's priority order asks -- and the filename
    importance criterion still gives a camera-prefixed name its small weighted
    bonus instead of an absolute veto.

    The full five-class taxonomy is kept for REPORTING: a label can still say
    "original-looking name" versus "neutral name" without that wording changing
    who survives.
    """
    return min(provenance, CLASS_NEUTRAL)


def gate_tier_of(filename: str) -> int:
    """Gate tier straight from a filename -- the call the engine needs."""
    return gate_tier(analyze_name(filename)['provenance'])

def is_machine_output(provenance: int) -> bool:
    """True when the name was written by a RECOVERY TOOL, not by a user.

    Round 21: this is the one class the date can never rescue. A carve such as
    'Recovered_jpg_file(2164).jpg' or 'img_1280x853x24_001092.jpg' has a name the
    recovery program invented -- it carries no identity whatsoever, so even a
    genuine EXIF timestamp inside it does not make it the user's original. The
    user's ruling was explicit: against a real camera or WhatsApp name, the real
    name wins, whatever the dates say.

    A copy marker is DIFFERENT and deliberately not included here: 'photo (96).jpg'
    and 'IMG-20180617-WA0051 (2).jpg' are real files the user owns, whose names
    still carry the true capture date -- the marker only says another copy exists.
    Those yield to the date when the gap is large (see effective_gate_tier).
    """
    return provenance <= CLASS_RECOVERED


def effective_gate_tier(provenance: int, date_decides: bool) -> int:
    """The tier the ranking actually compares, given whether the DATE decided.

    Round 21 fixed a real inversion of the user's priorities. The gate used to be
    ABSOLUTE, so it outranked the date criterion -- and the user's order puts DATE
    FIRST. Measured on the shipped reports that deleted
    'IMG-20180617-WA0051 (2).jpg' (2018-06-17) in favour of
    'IMG-20180707-WA0042.jpg' (2018-07-07) purely because of the '(2)', a 20-day
    regression. Worse, that '(2)' is a WhatsApp DOWNLOAD counter on a different
    message (WA0051 vs WA0042): it says nothing at all about that competitor.

    So the strength of the date evidence now decides which signal wins:

      date_decides=False  (no date contest, or a seconds/minutes/HOURS gap)
          -> the full gate applies. Such a gap means the same photo was saved or
             re-downloaded twice, so the timestamp cannot say which came first and
             the NAME is the only real evidence: the cleaner name survives.

      date_decides=True   (a gap of DAYS/months/years)
          -> every non-machine name is lifted to the SAME tier, so the gate stops
             vetoing and the weighted criteria decide -- date first, exactly as
             the configured priority order says. An older 'photo (96).jpg'
             therefore survives against a newer 'photo.jpg'.

    Machine output stays at the bottom in BOTH cases -- see is_machine_output().
    """
    if is_machine_output(provenance):
        return CLASS_RECOVERED
    if date_decides:
        return CLASS_NEUTRAL
    return gate_tier(provenance)


def name_gate_date_gap_seconds(hours) -> float:
    """Normalise the configured threshold to seconds (never negative)."""
    try:
        value = float(hours)
    except (TypeError, ValueError):
        value = 24.0
    return max(0.0, value) * 3600.0


def class_label(provenance: int) -> str:
    """Localized label for a class, for report lines."""
    key, english, arabic = CLASS_LABELS.get(provenance, CLASS_LABELS[CLASS_NEUTRAL])
    return _text(key, english, arabic)

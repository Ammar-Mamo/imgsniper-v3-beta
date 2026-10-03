"""
Round 14: never let a keystroke typed while the program was BUSY answer a later
prompt.

The Windows console queues keys pressed while the process is doing something
else and hands the whole queue to the next read. During a long similarity run a
user who pressed Enter a few times at a frozen screen therefore auto-answered
every prompt that came afterwards:

    input("Press any key to continue...")   <- swallowed one Enter, never waited
    IntPrompt.ask(default="0")              <- swallowed another -> "0" -> EXIT

so a 55-minute scan ended with the program closing "by itself", and the leftover
Enters were echoed back by PowerShell. The same queue could just as well answer
a DELETION confirmation nobody actually typed, which is the dangerous half.

Every CLI prompt now drains the queue first, so each one waits for a fresh,
deliberate keypress. Nothing else changes: the prompts, their wording and their
defaults are exactly as they were.
"""

import sys


def flush_pending_input() -> None:
    """Discard keystrokes already sitting in the console input queue.

    Best-effort by design. When stdin is redirected (a pipe, a test harness) or
    the platform offers no way to peek, there is nothing to drain and doing
    nothing is the only correct answer -- this must never raise into a prompt.
    """
    try:
        stdin = sys.stdin
        if stdin is None or not stdin.isatty():
            return

        if sys.platform == 'win32':
            import msvcrt

            while msvcrt.kbhit():
                msvcrt.getwch()
            return

        import os
        import select

        while select.select([stdin], [], [], 0)[0]:
            if not os.read(stdin.fileno(), 4096):
                break
    except Exception:      # pragma: no cover - defensive, never block a prompt
        pass


def ask_line(prompt: str) -> str:
    """``input(prompt)`` with the pending-key queue drained first."""
    flush_pending_input()
    return input(prompt)


def pause(prompt: str) -> None:
    """Wait for a FRESH keypress before returning to the menu."""
    ask_line(prompt)

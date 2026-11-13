"""Extracted from tests/test_services.py.

    ToolCallSpy was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import subprocess


class ToolCallSpy:
    """Record every archive-tool command line, and optionally fake one of them.

    The argv is the only place the conversion's real settings are visible - the password it was handed, the
    compression level it chose, the lock marker it was told to leave out - so the tests read them off the
    calls rather than off the log, which only carries the consequences. `intercept` receives the argv, the
    Popen kwargs and the real Popen; anything it returns stands in for that one call and everything else
    really runs, which is what lets a build be faked while its extraction still produces something real.
    """

    def __init__(self, intercept=None):
        self.calls = []
        self.intercept = intercept
        self._real = subprocess.Popen

    def __enter__(self):
        def spy(argv, *args, **kwargs):
            self.calls.append(list(argv))
            if self.intercept is not None:
                replacement = self.intercept(list(argv), kwargs, self._real)
                if replacement is not None:
                    return replacement
            return self._real(argv, *args, **kwargs)

        subprocess.Popen = spy
        return self

    def __exit__(self, *exc):
        subprocess.Popen = self._real
        return False

    def argv_containing(self, needle):
        """The recorded command lines that carry `needle`, for the common 'was -p passed?' assertion."""
        return [call for call in self.calls if any(needle in part for part in call)]

    def commands(self, subcommand):
        """The argv of every call that ran `subcommand`, e.g. every extract."""
        return [call for call in self.calls if len(call) > 1 and call[1] == subcommand]

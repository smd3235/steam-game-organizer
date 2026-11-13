"""Extracted from tests/test_services.py.

    _FakeProc was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import os


class _FakeProc:
    """A finished subprocess: 7z died, here is its exit code and the bytes it printed on the way out.

    The output goes through a real pipe rather than a list because _run_tool() reads the child with
    os.read() on stdout.fileno() to pick its progress lines out of the stream. A stand-in that only had the
    lines would leave the reader with nothing to parse, the failure detail would come back empty, and the
    code under test would never see the 'Break signaled' it is supposed to recognise.
    """

    def __init__(self, returncode, stdout=b""):
        self.returncode = returncode
        self.args = []
        self.stderr = None
        read_fd, write_fd = os.pipe()
        if stdout:
            os.write(write_fd, stdout)
        os.close(write_fd)  # closed so the reader's next read returns EOF rather than blocking
        self.stdout = os.fdopen(read_fd, "rb")

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode

    def communicate(self, *args, **kwargs):
        return (self.stdout.read(), None)

    def kill(self):
        pass

    def terminate(self):
        pass

"""Thread-safe in-memory application state.

StateStore holds the single source of truth for what the UI is showing right now —
the current phase, the scan result, the selected game, and any error — and hands
callers deep copies so no caller can mutate the live state by accident.
"""
import threading
from copy import deepcopy
from .models import AppState

class StateStore:
    def __init__(self): self._state=AppState(); self._lock=threading.RLock()
    def get(self):
        # A deep copy means the caller can rearrange the returned dict without
        # touching what the UI or a background job is reading at the same moment.
        with self._lock: return deepcopy(self._state)
    def update(self,**changes):
        with self._lock:
            for k,v in changes.items(): setattr(self._state,k,v)
            return deepcopy(self._state)

"""A small in-process pub/sub bus decoupling background work from the UI.

Event carries a name and a payload; EventBus lets any component subscribe by name
and emit to every subscriber. Background jobs emit events so the scan feed, the
Done screen, and progress bars can react without knowing who produced them.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Event:
    name: str
    payload: dict[str, Any] = field(default_factory=dict)


class EventBus:
    def __init__(self):
        self._handlers = {}

    def subscribe(self, name, handler):
        self._handlers.setdefault(name, []).append(handler)
        return lambda: self.unsubscribe(name, handler)

    def unsubscribe(self, name, handler):
        try:
            self._handlers.get(name, []).remove(handler)
        except ValueError:
            pass

    def emit(self, event):
        # Handlers are copied into a tuple before calling, so a handler that
        # unsubscribes itself mid-emission cannot corrupt the list being walked.
        for handler in tuple(self._handlers.get(event.name, ())):
            handler(event)

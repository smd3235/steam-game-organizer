import unittest


import pytest
from app.events import EventBus,Event
from core.state import StateStore
@pytest.mark.notkinter
class TestStateEvents(unittest.TestCase):
 def test_event(self):
  bus=EventBus(); seen=[]; bus.subscribe("x",lambda e:seen.append(e.payload["n"])); bus.emit(Event("x",{"n":3})); self.assertEqual(seen,[3])
 def test_state_copy(self):
  s=StateStore(); a=s.get(); a.phase="bad"; self.assertEqual(s.get().phase,"idle")

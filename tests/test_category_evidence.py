"""The evidence half of category suggestion: what was chosen, why, and what lost.

suggest_category() has callers and pinned answers going back years, so its signature and
its bare-string return stay exactly as they were. The reasoning now lives in
suggest_category_with_evidence(), and the string function is a wrapper over it - which is
the property most of these tests pin, because a scoring pass copied into both functions is
the one way the two can drift apart."""

import ast
import copy
import dataclasses
import json
import threading
import unittest

import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from core.constants import (
    CategoryEvidence,
    UNSORTED_EVIDENCE,
    suggest_category,
    suggest_category_with_evidence,
)
from core.models import ArtworkResult, GameArchive, OrganizationDecision, ScanResult, SteamMatch
from core.state import StateStore

# TestControllerRecordsEvidence extracted to tests\test_controller_records_evidence.py — see that module for its definition.
from tests.test_controller_records_evidence import TestControllerRecordsEvidence
# TestEvidenceShape extracted to tests\test_evidence_shape.py — see that module for its definition.
from tests.test_evidence_shape import TestEvidenceShape
ROOT = Path(__file__).resolve().parents[1]

# (args, expected) - every expected value is the answer the pre-evidence implementation
# gave, pinned here so that carrying the reason around cannot quietly change the folder a
# game lands in. The first block is the suite in test_services.py restated; the second is
# the edges that suite does not reach.
CASES = [
    ((["Indie", "Simulation"],), "Simulation"),
    ((["Indie"],), "Unsorted"),
    ((["Indie", "Horror"], "Haunted House", "A terrifying survival game"), "Horror"),
    ((["Indie", "Simulation"], "Factory Game", "Automate production", ["Automation", "Factory"]), "Automation"),
    ((["Indie", "Simulation"], "Idle Game", "An incremental clicker game", ["Clicker", "Incremental"]), "Idle"),
    ((["Indie", "Early Access"],), "Unsorted"),
    ((["City Sim"],), "City Builder"),
    ((["Simulation"], "Alpha Forge", "Build and manage a factory with automation"), "Automation"),
    ((["Simulation"], "Timberborn", "A sandbox city-building game"), "City Builder"),
    ((["Simulation"], "Cloud Dwellers", "A 2D simulation and city-building game"), "City Builder"),
    ((["Simulation"], "Flotsam", "Rescue survivors in a vibrant floating city-builder"), "City Builder"),
    ((["Simulation"], "Tactical Game", "A strategic tactical game", ["Idle"]), "Strategy"),
    ((["Simulation"], "Money Shop", "Run your own shop and manage store inventory"), "Shop Management"),
    ((["Simulation"], "Empire Tycoon", "Build your business empire from nothing"), "Tycoon"),
    ((["Action"], "Iron Souls", "A punishing combat souls-like adventure"), "Soulslike"),
    ((["Action"], "Cave Runner", "A metroidvania with backtracking exploration"), "Metroidvania"),
    ((["Action"], "Neon Rally", "A first-person shooter fps game"), "First-Person Shooter"),
    ((["Action"], "Iron Fists", "A fighting game with combo-based combat"), "Fighting"),
    ((["Adventure"], "Quiet Roads", "A narrative walking simulator"), "Walking Sim"),
    ((["Casual"], "Chart Topper", "A rhythm game beat-matching to music"), "Rhythm"),
    ((["Indie", "Simulation"], "Valheim", "A brutal survival crafting game, gather resources and build a base"), "Survival"),
    ((["Indie", "Simulation"], "Palworld", "Craft, build a base and survive Pals in a voxel world"), "Survival"),
    ((["Indie", "Casual"], "Brotato", "A bullet heaven survivors-like game with auto attacks and waves of enemies"), "Bullet Heaven"),
    ((["Indie", "Horror"], "Dead by Daylight", "A terrifying asymmetric survival horror game"), "Horror"),
    ((["Indie", "Simulation"], "Tidy Up", "A relaxing game about cleaning and decluttering your shop"), "Tidy Up"),
    ((["Indie", "Casual"], "Cleaning Up The Puzzle Gallery", "Sort, sweep and tidy up a puzzle museum"), "Tidy Up"),
    ((None,), "Unsorted"),
    ((["   "],), "Unsorted"),
    ((["Indie", "Early Access", "Free to Play"],), "Unsorted"),
    ((["Colony Sim"],), "City Builder"),
    ((["Roguelite"],), "Roguelike"),
    ((["Indie"], "Whatever", "Nothing here", ["Farming"]), "Farming"),
    ((["Simulation"], "Plain Title", "An ordinary description"), "Simulation"),
]

@pytest.mark.notkinter

class TestEvidenceIsSafeToCarry(unittest.TestCase):
    def _evidence(self):
        return suggest_category_with_evidence(["Simulation"], "Alpha Forge", "Build and manage a factory with automation")[1]

    def test_the_value_survives_deepcopy(self):
        evidence = self._evidence()
        self.assertEqual(copy.deepcopy(evidence), evidence)
        # The real machinery: StateStore deepcopies the whole state tree on every read.
        archive = GameArchive(Path("/tmp/Game.zip"), "Game", "Game", "game", ".zip")
        archive.decision.evidence = evidence
        store = StateStore()
        store.update(scan_result=ScanResult(archives=[archive]))
        self.assertEqual(store.get().scan_result.archives[0].decision.evidence, evidence)

    def test_the_value_is_json_native(self):
        payload = json.dumps(dataclasses.asdict(self._evidence()))
        self.assertEqual(json.loads(payload), {"chosen": "Automation", "score": 104,
                                               "basis": "description",
                                               "terms": ["automation", "factory",
                                                         "build and manage a factory"],
                                               "runners_up": [["Simulation", 54]],
                                               "considered": 2})

    def test_the_value_is_frozen(self):
        evidence = suggest_category_with_evidence(["Simulation"], "Plain Title", "An ordinary description")[1]
        with self.assertRaises(dataclasses.FrozenInstanceError):
            evidence.chosen = "RPG"

    def test_a_decision_defaults_to_the_fallback_evidence(self):
        self.assertEqual(OrganizationDecision().evidence, UNSORTED_EVIDENCE)

if __name__ == "__main__":
    unittest.main()

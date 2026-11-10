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

ROOT = Path(__file__).resolve().parents[1]

# (args, expected) - every expected value is the answer the pre-evidence implementation
# gave, pinned here so that carrying the reason around cannot quietly change the folder a
# game lands in. The first block is the suite in test_services.py restated; the second is
# the edges that suite does not reach.
CASES = [
    ((['Indie', 'Simulation'],), 'Simulation'),
    ((['Indie'],), 'Unsorted'),
    ((['Indie', 'Horror'], 'Haunted House', 'A terrifying survival game'), 'Horror'),
    ((['Indie', 'Simulation'], 'Factory Game', 'Automate production', ['Automation', 'Factory']), 'Automation'),
    ((['Indie', 'Simulation'], 'Idle Game', 'An incremental clicker game', ['Clicker', 'Incremental']), 'Idle'),
    ((['Indie', 'Early Access'],), 'Unsorted'),
    ((['City Sim'],), 'City Builder'),
    ((['Simulation'], 'Captain of Industry', 'Build and manage a factory with automation'), 'Automation'),
    ((['Simulation'], 'Timberborn', 'A sandbox city-building game'), 'City Builder'),
    ((['Simulation'], 'Cloud Dwellers', 'A 2D simulation and city-building game'), 'City Builder'),
    ((['Simulation'], 'Flotsam', 'Rescue survivors in a vibrant floating city-builder'), 'City Builder'),
    ((['Simulation'], 'Tactical Game', 'A strategic tactical game', ['Idle']), 'Strategy'),
    ((['Simulation'], 'Money Shop', 'Run your own shop and manage store inventory'), 'Shop Management'),
    ((['Simulation'], 'Empire Tycoon', 'Build your business empire from nothing'), 'Tycoon'),
    ((['Action'], 'Iron Souls', 'A punishing combat souls-like adventure'), 'Soulslike'),
    ((['Action'], 'Cave Runner', 'A metroidvania with backtracking exploration'), 'Metroidvania'),
    ((['Action'], 'Neon Rally', 'A first-person shooter fps game'), 'First-Person Shooter'),
    ((['Action'], 'Iron Fists', 'A fighting game with combo-based combat'), 'Fighting'),
    ((['Adventure'], 'Quiet Roads', 'A narrative walking simulator'), 'Walking Sim'),
    ((['Casual'], 'Chart Topper', 'A rhythm game beat-matching to music'), 'Rhythm'),
    ((['Indie', 'Simulation'], 'Valheim', 'A brutal survival crafting game, gather resources and build a base'), 'Survival'),
    ((['Indie', 'Simulation'], 'Palworld', 'Craft, build a base and survive Pals in a voxel world'), 'Survival'),
    ((['Indie', 'Casual'], 'Brotato', 'A bullet heaven survivors-like game with auto attacks and waves of enemies'), 'Bullet Heaven'),
    ((['Indie', 'Horror'], 'Dead by Daylight', 'A terrifying asymmetric survival horror game'), 'Horror'),
    ((['Indie', 'Simulation'], 'Tidy Up', 'A relaxing game about cleaning and decluttering your shop'), 'Tidy Up'),
    ((['Indie', 'Casual'], 'Cleaning Up The Puzzle Gallery', 'Sort, sweep and tidy up a puzzle museum'), 'Tidy Up'),
    ((None,), 'Unsorted'),
    ((['   '],), 'Unsorted'),
    ((['Indie', 'Early Access', 'Free to Play'],), 'Unsorted'),
    ((['Colony Sim'],), 'City Builder'),
    ((['Roguelite'],), 'Roguelike'),
    ((['Indie'], 'Whatever', 'Nothing here', ['Farming']), 'Farming'),
    ((['Simulation'], 'Plain Title', 'An ordinary description'), 'Simulation'),
]


@pytest.mark.notkinter
class TestTheTwoPathsAgree(unittest.TestCase):
    def test_the_string_and_evidence_paths_give_the_same_category(self):
        for args, expected in CASES:
            with self.subTest(case=args):
                category, evidence = suggest_category_with_evidence(*args)
                self.assertEqual(category, expected, 'the evidence path changed the answer for %r' % (args,))
                self.assertEqual(suggest_category(*args), expected, 'the string path changed the answer for %r' % (args,))
                self.assertEqual(evidence.chosen, expected, 'the evidence names a different category than the function returned')

    def test_the_string_function_is_a_pure_wrapper(self):
        """The scoring has to live in one place. Asserted on the parsed code, because the
        wrapper's body is the whole contract: a docstring and one delegated return."""
        tree = ast.parse((ROOT / 'core' / 'constants.py').read_text(encoding='utf-8'))
        functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        body = functions['suggest_category'].body
        self.assertEqual(len(body), 2, 'suggest_category is a docstring plus one delegated return, nothing else')
        self.assertIsInstance(body[0], ast.Expr, 'the first statement is the docstring')
        returned = body[1].value
        self.assertIsInstance(returned, ast.Subscript, 'suggest_category returns the delegated pair sliced to its first element')
        self.assertIsInstance(returned.value, ast.Call)
        self.assertEqual(ast.unparse(returned.value.func), 'suggest_category_with_evidence')

    def test_the_scoring_tables_are_defined_inside_one_function_only(self):
        """Each scoring table is assigned exactly once in the module, inside the evidence
        function - a second copy of the logic would show up here as a second owner."""
        tree = ast.parse((ROOT / 'core' / 'constants.py').read_text(encoding='utf-8'))
        owners = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Assign):
                    continue
                for target in sub.targets:
                    if isinstance(target, ast.Name) and target.id in ('inferred', 'priority', 'specificity'):
                        owners.setdefault(target.id, set()).add(node.name)
        for name in ('inferred', 'priority', 'specificity'):
            self.assertEqual(owners.get(name), {'suggest_category_with_evidence'},
                             'the %s table is defined outside the evidence function' % name)


class TestEvidenceShape(unittest.TestCase):
    def test_a_description_win_names_the_rule_and_its_keywords(self):
        category, evidence = suggest_category_with_evidence(
            ['Simulation'], 'Captain of Industry', 'Build and manage a factory with automation')
        self.assertEqual(category, 'Automation')
        self.assertEqual(evidence, CategoryEvidence(
            chosen='Automation', score=104, basis='description',
            terms=('automation', 'factory', 'build and manage a factory'),
            runners_up=(('Simulation', 54),), considered=2))

    def test_a_tag_win_is_a_rule_that_only_saw_tags_or_steam_categories(self):
        # An ignored genre leaves the field to the rule, so a hit that only the tags
        # knew about is reachable and must say so.
        category, evidence = suggest_category_with_evidence(
            ['Indie'], 'Whatever', 'Nothing here', tags=['Farming'])
        self.assertEqual(category, 'Farming')
        self.assertEqual(evidence, CategoryEvidence(
            chosen='Farming', score=38, basis='tag', terms=('farming',),
            runners_up=(), considered=1))

    def test_a_genre_win_carries_no_terms(self):
        category, evidence = suggest_category_with_evidence(
            ['Simulation'], 'Plain Title', 'An ordinary description')
        self.assertEqual(category, 'Simulation')
        self.assertEqual(evidence, CategoryEvidence(
            chosen='Simulation', score=54, basis='genre', terms=(),
            runners_up=(), considered=1))

    def test_a_genre_that_also_scored_as_a_rule_is_one_candidate(self):
        # "terrifying" feeds both the Horror rule and the Horror genre's own evidence
        # bonus. The genre pass out-scores the rule here, and the rule's score must not
        # resurface as a runner-up under the name that already won.
        category, evidence = suggest_category_with_evidence(
            ['Horror'], 'Haunted House', 'A terrifying survival game')
        self.assertEqual(category, 'Horror')
        self.assertEqual(evidence.basis, 'genre')
        self.assertEqual(evidence.terms, ())
        self.assertEqual(evidence.score, 115)
        self.assertEqual(evidence.runners_up, ())
        self.assertEqual(evidence.considered, 1)

    def test_runners_up_are_capped_at_three_and_ordered_by_score_then_name(self):
        # Five rules tie at 85; Horror is the earliest in the rule table, so it wins and
        # the other four are runners-up, of which only three fit, by score then name.
        category, evidence = suggest_category_with_evidence(
            ['Indie'], 'Horror Puzzle Tactical Explore Stealth', '')
        self.assertEqual(category, 'Horror')
        self.assertEqual(evidence.terms, ('horror',))
        self.assertEqual(evidence.runners_up,
                         (('Adventure', 85), ('Puzzle', 85), ('Stealth', 85)),
                         'runners_up must hold at most three, by score descending then name')
        self.assertEqual(evidence.considered, 5)

    def test_a_tie_is_won_by_the_rule_tested_first_and_lost_by_the_other(self):
        # Tidy Up and Puzzle both score 85; Tidy Up is earlier in the rule table, so it
        # wins and Puzzle is the runner-up at the same score.
        category, evidence = suggest_category_with_evidence(
            ['Indie', 'Casual'], 'Cleaning Up The Puzzle Gallery', 'Sort, sweep and tidy up a puzzle museum')
        self.assertEqual(category, 'Tidy Up')
        self.assertEqual(evidence.basis, 'description')
        self.assertEqual(evidence.terms, ('tidy up',))
        self.assertEqual(evidence.runners_up, (('Puzzle', 85), ('Casual', 19)))

    def test_every_path_to_unsorted_gives_the_same_fallback_evidence(self):
        for args in (([],), (None,), (['Indie'],), (['Indie', 'Early Access'],)):
            with self.subTest(case=args):
                self.assertEqual(suggest_category_with_evidence(*args),
                                 ('Unsorted', UNSORTED_EVIDENCE))
        self.assertEqual(UNSORTED_EVIDENCE, CategoryEvidence(
            chosen='Unsorted', score=0, basis='fallback', terms=(), runners_up=(), considered=0))


class TestEvidenceIsSafeToCarry(unittest.TestCase):
    def _evidence(self):
        return suggest_category_with_evidence(
            ['Simulation'], 'Captain of Industry', 'Build and manage a factory with automation')[1]

    def test_the_value_survives_deepcopy(self):
        evidence = self._evidence()
        self.assertEqual(copy.deepcopy(evidence), evidence)
        # The real machinery: StateStore deepcopies the whole state tree on every read.
        archive = GameArchive(Path('/tmp/Game.zip'), 'Game', 'Game', 'game', '.zip')
        archive.decision.evidence = evidence
        store = StateStore()
        store.update(scan_result=ScanResult(archives=[archive]))
        self.assertEqual(store.get().scan_result.archives[0].decision.evidence, evidence)

    def test_the_value_is_json_native(self):
        payload = json.dumps(dataclasses.asdict(self._evidence()))
        self.assertEqual(json.loads(payload), {
            'chosen': 'Automation', 'score': 104, 'basis': 'description',
            'terms': ['automation', 'factory', 'build and manage a factory'],
            'runners_up': [['Simulation', 54]], 'considered': 2})

    def test_the_value_is_frozen(self):
        evidence = suggest_category_with_evidence(
            ['Simulation'], 'Plain Title', 'An ordinary description')[1]
        with self.assertRaises(dataclasses.FrozenInstanceError):
            evidence.chosen = 'RPG'

    def test_a_decision_defaults_to_the_fallback_evidence(self):
        self.assertEqual(OrganizationDecision().evidence, UNSORTED_EVIDENCE)


class TestControllerRecordsEvidence(unittest.TestCase):
    """Both call sites have to attach the evidence to the decision, and the evidence has
    to describe the computed suggestion even when a remembered category replaces it."""

    class _Steam:
        def __init__(self, found=True):
            self.found = found

        def lookup(self, title, ctx, archive_path=None, refresh=False):
            if not self.found:
                return SteamMatch(found=False)
            return SteamMatch(found=True, appid='1', name='Factory Game',
                              description='Automate production', genres=['Indie', 'Simulation'],
                              tags=['Automation', 'Factory'], categories=['Automation'])

        def remember(self, title, steam_match):
            pass

    class _Artwork:
        def download_assets(self, *args, **kwargs):
            return ArtworkResult(status='not_requested')

        def lookup(self, appid):
            return ArtworkResult(status='not_requested')

    def _controller(self, logger, jobs, steam):
        from app.controller import AppController
        from app.events import EventBus
        services = type('Services', (), {'steam': steam, 'artwork': self._Artwork()})()
        return AppController(StateStore(), EventBus(), logger, services, jobs)

    def _archive(self):
        return GameArchive(Path('/tmp/Factory.zip'), 'Factory Game', 'Factory Game', 'factory', '.zip')

    def _run(self, method, *args):
        # _submit() hands back only the JobContext, not the future, so the
        # result is captured through the done callback the job invokes.
        finished = threading.Event()
        captured = {}

        def done(result):
            captured['result'] = result
            finished.set()

        method(*args, done)
        self.assertTrue(finished.wait(timeout=30), 'the verify job never finished')
        return captured['result']

    def test_verify_all_attaches_the_evidence_to_the_decision(self):
        from app.jobs import JobManager
        from core.logger import AppLogger
        with TemporaryDirectory() as d:
            logger = AppLogger(Path(d) / 'x.log'); jobs = JobManager()
            controller = self._controller(logger, jobs, self._Steam())
            results = self._run(controller.verify_all, [self._archive()], lambda *a: None)
            self.assertEqual(results[0].decision.category, 'Automation')
            self.assertEqual(results[0].decision.suggested_category, 'Automation')
            self.assertEqual(results[0].decision.evidence, CategoryEvidence(
                chosen='Automation', score=101, basis='description',
                terms=('automate', 'factory'), runners_up=(('Simulation', 53),), considered=2))
            jobs.shutdown()

    def test_verify_one_attaches_the_evidence_to_the_decision(self):
        from app.jobs import JobManager
        from core.logger import AppLogger
        with TemporaryDirectory() as d:
            logger = AppLogger(Path(d) / 'x.log'); jobs = JobManager()
            controller = self._controller(logger, jobs, self._Steam())
            result = self._run(controller.verify_one, self._archive(), 'Factory Game')
            self.assertEqual(result.decision.category, 'Automation')
            self.assertEqual(result.decision.suggested_category, 'Automation')
            self.assertEqual(result.decision.evidence, CategoryEvidence(
                chosen='Automation', score=101, basis='description',
                terms=('automate', 'factory'), runners_up=(('Simulation', 53),), considered=2))
            self.assertEqual(result.decision.accepted, False)
            jobs.shutdown()

    def test_a_remembered_category_replaces_the_category_but_not_the_evidence(self):
        from app.jobs import JobManager
        from core.logger import AppLogger
        with TemporaryDirectory() as d:
            logger = AppLogger(Path(d) / 'x.log'); jobs = JobManager()
            controller = self._controller(logger, jobs, self._Steam())
            controller.config = type('Config', (), {'config_dir': Path(d), 'sync_to_appdata': lambda self: None})()
            controller.remember_category('factory', 'Adventure')
            results = self._run(controller.verify_all, [self._archive()], lambda *a: None)
            # The combobox shows the remembered folder...
            self.assertEqual(results[0].decision.category, 'Adventure')
            # ...while the suggestion, and the evidence beside it, still describe the
            # computed answer.
            self.assertEqual(results[0].decision.suggested_category, 'Automation')
            self.assertEqual(results[0].decision.evidence.chosen, 'Automation')
            self.assertEqual(results[0].decision.evidence.basis, 'description')
            jobs.shutdown()

    def test_a_game_the_steam_lookup_misses_gets_fallback_evidence(self):
        from app.jobs import JobManager
        from core.logger import AppLogger
        with TemporaryDirectory() as d:
            logger = AppLogger(Path(d) / 'x.log'); jobs = JobManager()
            controller = self._controller(logger, jobs, self._Steam(found=False))
            results = self._run(controller.verify_all, [self._archive()], lambda *a: None)
            self.assertEqual(results[0].decision.category, 'Unsorted')
            self.assertEqual(results[0].decision.evidence, UNSORTED_EVIDENCE)
            jobs.shutdown()

    def test_the_debug_log_reports_the_rule_that_won(self):
        from app.jobs import JobManager
        from core.logger import AppLogger
        with TemporaryDirectory() as d:
            logger = AppLogger(Path(d) / 'x.log'); jobs = JobManager()
            controller = self._controller(logger, jobs, self._Steam())
            with patch.object(logger, 'debug') as debug:
                self._run(controller.verify_all, [self._archive()], lambda *a: None)
            messages = [call.args[1] for call in debug.call_args_list
                        if call.args and call.args[0] == 'CATEGORY']
            self.assertTrue(any('basis=[description]' in m and 'terms=[automate|factory]' in m
                                and 'runners_up=[Simulation:53]' in m for m in messages),
                            'the debug log no longer says which rule won and what it matched: %r' % (messages,))
            jobs.shutdown()


if __name__ == '__main__':
    unittest.main()

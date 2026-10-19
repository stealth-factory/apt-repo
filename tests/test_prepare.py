from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import prepare


class PrepareTests(unittest.TestCase):
    def event(self):
        return {'action': 'opscope-release', 'client_payload': {
            'repository': 'stealth-factory/opscope', 'tag': 'v1.2.3', 'commit': 'a' * 40}}

    def test_dispatch_requires_exact_allowlisted_source_tag_and_commit(self):
        self.assertEqual(prepare.request('repository_dispatch', self.event()), ('opscope', 'v1.2.3', 'a' * 40))
        for key, value in [('repository', 'other/repo'), ('tag', 'main'), ('tag', 'v1.2.3-rc.1'),
                           ('tag', 'v1.2.3\n'), ('commit', 'main'), ('commit', None)]:
            event = self.event(); event['client_payload'][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                prepare.request('repository_dispatch', event)
        event = self.event(); event['client_payload']['token'] = 'not-accepted'
        with self.assertRaises(ValueError): prepare.request('repository_dispatch', event)
        event = self.event(); event['action'] = 'other'
        with self.assertRaises(ValueError): prepare.request('repository_dispatch', event)
        event = self.event(); del event['action']
        with self.assertRaises(ValueError): prepare.request('repository_dispatch', event)

    def test_each_dispatch_type_selects_only_its_own_package_source(self):
        event = {'action': 'gh-pr-manager-release', 'client_payload': {
            'repository': 'stealth-factory/gh-pr-manager', 'tag': 'v0.1.0', 'commit': 'b' * 40}}
        self.assertEqual(prepare.request('repository_dispatch', event), ('gh-pr-manager', 'v0.1.0', 'b' * 40))
        # A valid source under the other package's dispatch type is refused.
        for action, repository in [('gh-pr-manager-release', 'stealth-factory/opscope'),
                                   ('opscope-release', 'stealth-factory/gh-pr-manager')]:
            event = self.event(); event['action'] = action; event['client_payload']['repository'] = repository
            with self.subTest(action=action), self.assertRaisesRegex(ValueError, 'release source'):
                prepare.request('repository_dispatch', event)

    def test_dispatch_types_are_unique_per_package(self):
        types = [config['dispatch'] for config in prepare.registry().values()]
        self.assertEqual(len(types), len(set(types)))
        self.assertEqual(prepare.registry()['opscope']['dispatch'], 'opscope-release')
        self.assertEqual(prepare.registry()['gh-pr-manager']['dispatch'], 'gh-pr-manager-release')

    def test_schedule_refreshes_only_existing_metadata(self):
        with tempfile.TemporaryDirectory() as root, patch.object(prepare, 'fetch_release') as fetch, patch.object(prepare, 'indexes') as indexes:
            prepare.prepare('schedule', {}, Path(root))
            fetch.assert_not_called()
            indexes.assert_called_once_with(Path(root).resolve())

    def test_metadata_refresh_is_monthly_on_first_at_1930_taipei_and_release_dispatch_is_immediate(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/publish.yml').read_text()
        self.assertEqual(workflow.count('cron:'), 1)
        self.assertIn("cron: '30 11 1 * *'", workflow)
        self.assertIn('    types: [opscope-release, gh-pr-manager-release]\n', workflow)

    def test_workflow_triggers_cover_exactly_the_registry(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/publish.yml').read_text()
        registry = prepare.registry()
        types = ', '.join(config['dispatch'] for config in registry.values())
        self.assertEqual(workflow.count('    types: ['), 1)
        self.assertIn(f'    types: [{types}]\n', workflow)
        self.assertEqual(workflow.count('        options: ['), 1)
        self.assertIn(f"        options: [{', '.join(registry)}]\n", workflow)

    def test_manual_recovery_requires_exact_package_and_tag(self):
        self.assertEqual(prepare.request('workflow_dispatch', {'inputs': {'package': 'opscope', 'tag': 'v1.2.3'}}), ('opscope', 'v1.2.3', None))
        self.assertEqual(prepare.request('workflow_dispatch', {'inputs': {'package': 'gh-pr-manager', 'tag': 'v0.1.0'}}), ('gh-pr-manager', 'v0.1.0', None))
        for inputs in [{}, {'package': 'other', 'tag': 'v1.2.3'}, {'package': 'opscope', 'tag': 'latest'}]:
            with self.assertRaises(ValueError): prepare.request('workflow_dispatch', {'inputs': inputs})
        with self.assertRaises(ValueError): prepare.request('pull_request', {})


if __name__ == '__main__':
    unittest.main()

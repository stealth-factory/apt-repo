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

    def test_schedule_refreshes_only_existing_metadata(self):
        with tempfile.TemporaryDirectory() as root, patch.object(prepare, 'fetch_release') as fetch, patch.object(prepare, 'indexes') as indexes:
            prepare.prepare('schedule', {}, Path(root))
            fetch.assert_not_called()
            indexes.assert_called_once_with(Path(root).resolve())

    def test_manual_recovery_requires_exact_package_and_tag(self):
        self.assertEqual(prepare.request('workflow_dispatch', {'inputs': {'package': 'opscope', 'tag': 'v1.2.3'}}), ('opscope', 'v1.2.3', None))
        for inputs in [{}, {'package': 'other', 'tag': 'v1.2.3'}, {'package': 'opscope', 'tag': 'latest'}]:
            with self.assertRaises(ValueError): prepare.request('workflow_dispatch', {'inputs': inputs})
        with self.assertRaises(ValueError): prepare.request('pull_request', {})


if __name__ == '__main__':
    unittest.main()

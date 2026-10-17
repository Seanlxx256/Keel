import json
import unittest
from keel.observations import workspace_frames
from examples.run_transition_task import baseline_observations


class ObservedFrameTests(unittest.TestCase):
    def test_observed_paths_survive_empty_error_message_without_source_lines(self):
        trace = 'File "/workspace/django/contrib/staticfiles/handlers.py", line 59\n    SECRET_SOURCE()\nFile "/usr/local/lib/a.py", line 2\n'
        execution = {'stdout': json.dumps({'records': [{'case': 'one', 'passed': False,
                     'type': 'BrokenBarrierError', 'message': '', 'traceback': trace}]})}
        result = baseline_observations(execution)
        self.assertEqual(result['source_frames'], [{'path': 'django/contrib/staticfiles/handlers.py', 'line': 59}])
        self.assertNotIn('SECRET_SOURCE', json.dumps(result))
        self.assertNotIn('source_frames', baseline_observations(execution, include_frames=False))

    def test_paths_cannot_escape_and_positions_are_bounded(self):
        trace = '\n'.join(f'File "/workspace/{name}", line {line}' for name, line in [
            ('../secret.py', 1), ('a/../../x.py', 2), ('C:/a.py', 3), ('x.py', 0), ('x.py', 10000001), ('safe.py', 5)])
        self.assertEqual(workspace_frames(trace)[0], [{'path': 'safe.py', 'line': 5}])

    def test_duplicate_frames_and_truncation_are_explicit(self):
        trace = '\n'.join(f'File "/workspace/a{i}.py", line 1' for i in range(12))
        frames, omitted = workspace_frames(trace)
        self.assertTrue(omitted)
        self.assertEqual(len(frames), 8)
        self.assertEqual(frames[-1]['path'], 'a11.py')

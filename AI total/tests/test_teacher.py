import json
import tempfile
import unittest
from pathlib import Path

from ai_core import Engine
from web_ui import dispatch


class TeacherOverviewTests(unittest.TestCase):
    def test_overview_is_read_only_and_shows_only_final_grade(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine(None, directory)
            task = engine.sample()
            engine.approve(task['id'], 'Teacher')
            sid = engine.start(task['id'], 'Student')['id']
            session = engine.load(sid)
            session['teacher_decision'] = {'grade': 4}
            engine.save(session)
            before = {p.name: p.read_bytes() for p in Path(directory).rglob('*.json')}
            overview = dispatch(engine, 'teacher_overview', {})
            self.assertIsNone(overview['sessions'][0]['grade'])
            self.assertEqual(overview['sessions'][0]['student'], 'Student')
            self.assertNotIn('expected', json.dumps(overview))
            self.assertNotIn('history', overview['sessions'][0])
            self.assertEqual(before, {p.name: p.read_bytes() for p in Path(directory).rglob('*.json')})
            session['status'] = 'reviewed'
            engine.save(session)
            self.assertEqual(dispatch(engine, 'teacher_overview', {})['sessions'][0]['grade'], 4)

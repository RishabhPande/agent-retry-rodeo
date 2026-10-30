import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

class SiteBuildTests(unittest.TestCase):
    def test_static_output_contains_only_replay_artifacts(self):
        path = Path(__file__).resolve().parents[1] / 'scripts/build_site.py'
        spec = importlib.util.spec_from_file_location('build_site', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            runs = module.build(folder)
            output = Path(folder)
            self.assertEqual({p.name for p in output.iterdir()}, {'index.html', 'results.json', '.nojekyll'})
            self.assertEqual(json.loads((output / 'results.json').read_text()), runs)
            self.assertEqual(len(runs), 6)
            self.assertIn('not LLM benchmark scores', (output / 'index.html').read_text())

import importlib.util
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]

class ReadmeVisualTests(unittest.TestCase):
    def test_walkthrough_is_reproducible_and_uses_actual_trace(self):
        spec = importlib.util.spec_from_file_location('build_readme_visuals', ROOT / 'scripts/build_readme_visuals.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'diagram.svg'
            result = module.build(output)
            self.assertEqual(output.read_bytes(), (ROOT / 'docs/assets/evidence-walkthrough.svg').read_bytes())
            self.assertTrue(result['claimed_complete'])
            self.assertTrue(result['false_completion'])
            self.assertFalse(result['success'])
            self.assertEqual(result['duplicate_comments'], 1)
            tree = ET.fromstring(output.read_text())
            text = ' '.join(tree.itertext())
            for event in result['events']:
                self.assertIn(event['action'], text)
            self.assertIn('No live model', text)
            self.assertIn('not a sandbox', text)

    def test_readme_visuals_exist_and_custom_runner_is_in_adapter_section(self):
        readme = (ROOT / 'README.md').read_text()
        self.assertEqual(readme.count('## Bring your agent'), 1)
        section = readme.split('## Bring your agent')[1].split('## Evidence, not a vibes judge')[0]
        self.assertIn('run --agent examples/my_agent.py', section)
        self.assertIn('not a sandbox', section)
        self.assertIn('docs/assets/evidence-walkthrough.svg', readme)
        self.assertIn('docs/assets/recovery-map.svg', readme)

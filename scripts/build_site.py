"""Build a static Pages artifact from fresh synthetic runs, never live accounts."""
from pathlib import Path
import argparse
import json
from agent_retry_rodeo.engine import load_scenario, run, NaiveAgent, RecoveryAgent
from agent_retry_rodeo.report import render

ROOT = Path(__file__).resolve().parents[1]

def build(output):
    scenarios = [load_scenario(path) for path in sorted((ROOT / 'scenarios').glob('*.yaml'))]
    if not scenarios or len({s['id'] for s in scenarios}) != len(scenarios):
        raise ValueError('Build requires a nonempty pack with unique scenario IDs')
    results = [run(s, a) for s in scenarios for a in (NaiveAgent(), RecoveryAgent())]
    # This specific teaching pack promises an intentional failure and recovery per case.
    if any(results[i]['success'] or not results[i + 1]['success'] for i in range(0, len(results), 2)):
        raise ValueError('Teaching baseline contract changed; review before deployment')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'index.html').write_text(render(results), encoding='utf-8')
    (output / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    (output / '.nojekyll').write_text('', encoding='utf-8')
    return results

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'site-output')
    args = parser.parse_args()
    results = build(args.output)
    print(f'Built {len(results)} scripted runs into {args.output.resolve()}')

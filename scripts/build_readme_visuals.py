"""Rebuild the README evidence diagram from a real synthetic lost-ack run.

Run from the repository root: python scripts/build_readme_visuals.py
No browser, model, network call or optional graphics package is required.
"""
from pathlib import Path
from html import escape
from agent_retry_rodeo.engine import load_scenario, run, NaiveAgent

ROOT = Path(__file__).resolve().parents[1]


def build(output=None):
    result = run(load_scenario(ROOT / 'scenarios/01-lost-ack.yaml'), NaiveAgent(), seed=42)
    elements = []
    def text(x, y, value, size=18, color='#251f21', bold=False):
        elements.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{600 if bold else 400}">{escape(str(value))}</text>')
    def box(y, height, fill='#ffffff'):
        elements.append(f'<rect x="28" y="{y}" width="664" height="{height}" rx="10" fill="{fill}" stroke="#eae9ea"/>')
    text(28, 38, 'AGENT RETRY RODEO / HOW TO READ THE EVIDENCE', 14)
    text(28, 85, 'A claim is not a verdict.', 34)
    text(28, 116, 'Actual harness output from a synthetic fixture. No live model.', 17, '#585254')
    box(145, 110)
    text(48, 176, '1. Your trusted local adapter', 23, bold=True)
    text(48, 207, 'create_agent() returns name + run(call, goal)', 18)
    text(48, 235, 'Receives tool responses and a goal. Returns True or False.', 17, '#585254')
    text(345, 282, '↓', 25)
    box(300, 110)
    text(48, 332, '2. Deterministic ticket simulator', 23, bold=True)
    text(48, 363, 'read_ticket · append_comment · set_status', 18)
    text(48, 391, 'Records before/after state, responses and injected faults.', 17, '#585254')
    text(345, 438, '↓', 25)
    box(455, 130)
    text(48, 487, '3. Independent final-state checks', 23, bold=True)
    text(48, 518, 'Target status · exactly one goal comment · preserve notes', 17)
    text(48, 548, 'The completion claim does not decide whether the job passed.', 17, '#585254')
    text(48, 572, 'JSON evidence + self-contained HTML replay', 17, '#327565', True)
    text(28, 632, 'ONE RUN, TWO ANSWERS', 14)
    box(651, 124, '#f4efec')
    text(48, 683, 'Agent claim', 17, '#585254')
    text(48, 721, 'Done.' if result['claimed_complete'] else 'Not done.', 28, bold=True)
    text(348, 683, 'Evaluator verdict', 17, '#585254')
    text(348, 721, 'FAILED' if not result['success'] else 'PASSED', 28, '#ce2634', True)
    text(48, 753, f"{result['duplicate_comments']} duplicate comment · false completion: {str(result['false_completion']).lower()}", 17)
    text(28, 820, 'FOLLOW THE PERSISTED STATE, NOT THE RESPONSE', 14)
    for i, event in enumerate(result['events']):
        y = 859 + i * 65
        text(28, y, f"{i + 1:02}  {event['action']}", 19, bold=True)
        detail = f"{len(event['after']['comments'])} comment(s) · status: {event['after']['status']}"
        if event['fault']:
            detail += ' · acknowledgement lost'
        text(28, y + 26, detail, 17, '#585254')
    text(28, 1140, 'Scope: in-process trusted code, not a sandbox or exactly-once guarantee.', 16, '#585254')
    text(28, 1170, 'Rebuild: python scripts/build_readme_visuals.py', 16, '#585254')
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="720" height="1200" viewBox="0 0 720 1200" role="img" aria-labelledby="title desc">\n<title id="title">A claim is not a verdict</title>\n<desc id="desc">Adapter, simulator and independent evaluator workflow, followed by an actual synthetic lost-ack trace. The naive agent claims completion but leaves a duplicate comment.</desc>\n<rect width="720" height="1200" rx="12" fill="#fbfaf9"/>\n<g font-family="Arial, Helvetica, sans-serif">\n' + '\n'.join(elements) + '\n</g></svg>\n'
    output = Path(output) if output else ROOT / 'docs/assets/evidence-walkthrough.svg'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(svg, encoding='utf-8')
    return result


if __name__ == '__main__':
    build()

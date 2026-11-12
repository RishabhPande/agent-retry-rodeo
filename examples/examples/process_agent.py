"""A scripted protocol client, not an LLM or production agent.

Replace the decision loop with your own trusted agent. Keep stdout JSON-only;
logs belong on stderr. A fresh process is launched for each scenario.
"""
import json
import sys


def send(frame):
    print(json.dumps(frame), flush=True)


def call(action, **params):
    send({'type': 'call', 'action': action, 'params': params})
    response = json.loads(sys.stdin.readline())
    if response['type'] != 'observation':
        raise ValueError('Expected observation')
    return response


def main():
    start = json.loads(sys.stdin.readline())
    if start['type'] != 'start' or start['protocol'] != 1:
        raise ValueError('Unsupported protocol')
    goal = start['goal']
    complete = False
    for _ in range(12):
        observed = call('read_ticket')
        if not observed['ok']:
            continue
        state = observed['result']
        if goal['comment'] not in state['comments']:
            call('append_comment', text=goal['comment'])
        elif state['status'] != goal['status']:
            response = call('set_status', status=goal['status'], expected_version=state['version'])
            if not response['ok'] and response['result'].get('via'):
                call('set_status', status=response['result']['via'], expected_version=state['version'])
        else:
            complete = True
            break
    send({'type': 'done', 'claimed_complete': complete})


if __name__ == '__main__':
    main()

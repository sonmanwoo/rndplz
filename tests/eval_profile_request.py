"""Evaluate profile_request.v1 on local Ollama with the mock sentences (not a unit test).

Runs ProfileReader.interpret, the server's own call and grounding, against a local model and
reports how many sentences end in the expected action, how many drafted a change the user did
not ask for (unwanted; the draft still needs the user's save), how many model values the
grounding dropped, and latency. Sets: profile_request_cases (tuning), _fresh and _compound
(written apart from the tuning).

    python tests/eval_profile_request.py --model gemma4:e4b [--cases tests/data/profile_request_fresh.jsonl]
"""
import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rndplz.chat_models import ChatModels  # noqa: E402
from rndplz.profile_reading import ProfileReader, ReadingError  # noqa: E402

CASES = Path(__file__).with_name('data') / 'profile_request_cases.jsonl'


class Local:
    """The worker's call on local Ollama; keeps the raw answer to count dropped values."""

    def __init__(self, model):
        self.models, self.model, self.raw = ChatModels({}), model, ''

    def get(self, identifier):
        return {'id': identifier, 'provider': 'bridge', 'model': self.model}

    def stream(self, identifier, messages, *, contract=None):
        self.raw = ''.join(self.models.stream('ollama:' + self.model, messages, contract=contract))
        yield self.raw


def norm(value):
    return re.sub(r'\s+', '', value).lower()


def verdict(case, plan):
    kinds = case['kind'] if isinstance(case['kind'], list) else [case['kind']]
    edits = sorted((a, f, norm(v)) for a, f, v in case['edits'])
    got = sorted((e['action'], e['field'], norm(e['value'])) for e in plan['edits'])
    titles = [c['title'] for c in plan['careers']]
    careers = len(titles) == len(case['careers']) and all(
        any(re.search(key, title) for title in titles) for key in case['careers'])
    return plan['kind'] in kinds and got == edits and careers


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', default='gemma4:e4b')
    parser.add_argument('--out', default='')
    parser.add_argument('--cases', default=str(CASES), help='JSON Lines file (default: the mock set)')
    args = parser.parse_args()
    local = Local(args.model)
    reader = ProfileReader(local)
    cases = [json.loads(line) for line in Path(args.cases).read_text(encoding='utf-8').splitlines() if line.strip()]
    rows, latencies, dropped = [], [], 0
    for case in cases:
        started = time.monotonic()
        try:
            plan = reader.interpret('bridge', case['text'], case['snapshot'])
        except (ReadingError, ValueError) as error:
            plan = {'kind': 'invalid:' + type(error).__name__, 'edits': [], 'careers': []}
        latencies.append(time.monotonic() - started)
        try:
            raw = json.loads(local.raw)
            proposed = len(raw.get('edits') or []) + len(raw.get('careers') or [])
        except (TypeError, ValueError, AttributeError):
            proposed = 0
        dropped += max(0, proposed - len(plan['edits']) - len(plan['careers']))
        unwanted = not case['edits'] and not case['careers'] and bool(plan['edits'] or plan['careers'])
        rows.append({**case, 'plan': plan, 'raw': local.raw, 'ok': verdict(case, plan), 'unwanted': unwanted})
    ok = sum(row['ok'] for row in rows)
    print(f"model={args.model} cases={len(rows)}")
    print(f"expected action {ok}/{len(rows)} = {ok / len(rows):.1%}")
    print(f"unwanted drafts (nothing to change, but a change drafted) {sum(row['unwanted'] for row in rows)}")
    print(f"model values dropped by grounding {dropped}")
    print(f"latency mean {statistics.mean(latencies):.2f}s max {max(latencies):.2f}s")
    for row in rows:
        if not row['ok']:
            print(f"  MISS {row['id']} {row['text']} :: {json.dumps(row['plan'], ensure_ascii=False)}")
    if args.out:
        Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()

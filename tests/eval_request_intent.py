"""Evaluate request_intent.v1 on local Ollama with the mock utterances (not a unit test).

Runs the same call the Gemma worker makes (ChatModels.stream with the contract) and
reports 3-class accuracy, the confusion matrix, routing accuracy (profile panel or
not) and latency.

    python tests/eval_request_intent.py --model gemma4:e4b [--think] [--repeat 1]
"""
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rndplz import chat_models, request_intent  # noqa: E402
from rndplz.chat_models import ChatModels  # noqa: E402
from rndplz.request_intent import INTENTS, IntentError, intent_messages, parse_intent  # noqa: E402

CASES = Path(__file__).with_name('data') / 'request_intent_cases.jsonl'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', default='gemma4:e4b')
    parser.add_argument('--think', action='store_true', help='keep model reasoning (default: off, as deployed)')
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--out', default='')
    parser.add_argument('--cases', default=str(CASES), help='JSON Lines file (default: the mock set)')
    args = parser.parse_args()
    if args.think:
        chat_models.OLLAMA_NO_THINK_CONTRACTS = chat_models.OLLAMA_NO_THINK_CONTRACTS - {request_intent.CONTRACT}
        base = request_intent.contract_spec
        request_intent.contract_spec = lambda: {**base(), 'max_tokens': 2048}
    models = ChatModels({})
    cases = [json.loads(line) for line in Path(args.cases).read_text(encoding='utf-8').splitlines() if line.strip()]
    rows, latencies = [], []
    for _ in range(args.repeat):
        for case in cases:
            messages = intent_messages(case['text'], attachments=case['attachments'], active_task=case['active_task'],
                                       recent_turns=[tuple(turn) for turn in case['recent_turns']])
            started = time.monotonic()
            try:
                raw = ''.join(models.stream('ollama:' + args.model, messages, contract=request_intent.CONTRACT))
                predicted = parse_intent(raw)
            except (IntentError, ValueError) as error:
                predicted = 'invalid:' + type(error).__name__
            latencies.append(time.monotonic() - started)
            rows.append({**case, 'predicted': predicted})
    confusion = {e: {p: 0 for p in (*INTENTS, 'invalid')} for e in INTENTS}
    for row in rows:
        confusion[row['expected']][row['predicted'] if row['predicted'] in INTENTS else 'invalid'] += 1
    correct = sum(row['predicted'] == row['expected'] for row in rows)
    routed = sum((row['predicted'] == 'profile_update') == (row['expected'] == 'profile_update') for row in rows)
    print(f"model={args.model} think={'on' if args.think else 'off'} cases={len(rows)}")
    print(f"3-class accuracy {correct}/{len(rows)} = {correct / len(rows):.1%}")
    print(f"routing accuracy (profile panel or not) {routed}/{len(rows)} = {routed / len(rows):.1%}")
    print('confusion (rows=expected, cols=predicted):')
    print('  ' + ' '.join(f'{p[:8]:>9}' for p in (*INTENTS, 'invalid')))
    for expected in INTENTS:
        print(f"  {expected[:8]:<9}" + ' '.join(f'{confusion[expected][p]:>9}' for p in (*INTENTS, 'invalid')))
    print(f"latency mean {statistics.mean(latencies):.2f}s p90 {sorted(latencies)[int(len(latencies) * .9) - 1]:.2f}s max {max(latencies):.2f}s")
    for row in rows:
        if row['predicted'] != row['expected']:
            print(f"  MISS {row['id']} expected={row['expected']} predicted={row['predicted']} :: {row['text']}")
    if args.out:
        Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()

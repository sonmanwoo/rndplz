"""Run the profile reader on a text file with local Ollama (not a unit test).

Same contracts and checks as the server (profile_reading.ProfileReader); prints timings and
writes the proposals as JSON for comparison with a reference reading.

    python tests/eval_profile_reading.py <document.txt> <out.json> --model gemma4:e4b
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rndplz.chat_models import ChatModels  # noqa: E402
from rndplz.profile_reading import ProfileReader, split_parts  # noqa: E402


class LocalModels:
    """The worker's call path (ChatModels.stream on Ollama) under the bridge provider name."""

    def __init__(self, model):
        self.inner, self.model = ChatModels({}), model

    def get(self, identifier):
        return {'id': identifier, 'provider': 'bridge', 'enabled': True}

    def stream(self, identifier, messages, *, contract=None):
        return self.inner.stream('ollama:' + self.model, messages, contract=contract)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('document')
    parser.add_argument('out')
    parser.add_argument('--model', default='gemma4:e4b')
    args = parser.parse_args()
    text = Path(args.document).read_text(encoding='utf-8')
    reader, snapshot = ProfileReader(LocalModels(args.model)), {'skills': [], 'interests': [], 'career_titles': []}
    parts = split_parts(text)
    candidates, timings, dropped_total = [], [], 0
    for index in range(1, len(parts) + 1):
        started = time.monotonic()
        kept, dropped = reader.read_part('bridge', Path(args.document).name, parts, index, snapshot)
        timings.append(round(time.monotonic() - started, 1))
        candidates += kept
        dropped_total += dropped
        print(f'part {index}/{len(parts)}: {timings[-1]}s kept {len(kept)} dropped {dropped}', flush=True)
    started = time.monotonic()
    proposals = reader.merge('bridge', candidates, snapshot, text)
    merge_seconds = round(time.monotonic() - started, 1)
    counts = {field: sum(p['field'] == field for p in proposals) for field in ('career', 'skills', 'interests')}
    print(f'merge: {merge_seconds}s -> {counts}; total {sum(timings) + merge_seconds:.0f}s; '
          f'candidates {len(candidates)} kept / {dropped_total} dropped (quote not in text)')
    Path(args.out).write_text(json.dumps({'model': args.model, 'parts': len(parts), 'part_seconds': timings,
                                          'merge_seconds': merge_seconds, 'candidates': candidates,
                                          'dropped': dropped_total, 'proposals': proposals}, ensure_ascii=False, indent=1),
                              encoding='utf-8')


if __name__ == '__main__':
    main()

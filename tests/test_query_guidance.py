"""The short-query guidance must reach every contract that lets the model write queries.

On 2026-09-23 gemma4:e4b copied a request sentence into one query
("TCB 솔벤트 증류 기술 잔존물 제거"); every term must match one record, so the
user's one-line career record containing "증류" was never found.
"""
import json
import unittest

from rndplz.model_dialogue import generation_contract


def query_descriptions(schema):
    """Yield every description attached to a `queries` field anywhere in a schema."""
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key == "queries" and isinstance(value, dict) and "description" in value:
                yield value["description"]
            yield from query_descriptions(value)
    elif isinstance(schema, list):
        for item in schema:
            yield from query_descriptions(item)


class QueryGuidanceTests(unittest.TestCase):
    def test_plan_and_response_schemas_carry_short_query_examples(self):
        for name in ("dialogue_plan.v2", "dialogue_response.v1", "dialogue_refine.v1"):
            found = list(query_descriptions(generation_contract(name)["format"]))
            self.assertTrue(found, name)
            for text in found:
                self.assertIn("1-2 words", text, name)
                self.assertIn("증류", text, name)
                self.assertIn("never copy a request sentence", text, name)

    def test_plan_system_prompt_explains_short_queries_in_korean(self):
        system = generation_contract("dialogue_plan.v2")["system"]
        self.assertIn("1~2어절 핵심 기술어", system)
        self.assertIn("TCB 솔벤트 증류 기술 잔존물 제거", system)
        self.assertIn("groups로 나누고", system)

    def test_query_item_limits_unchanged(self):
        schema = generation_contract("dialogue_plan.v2")["format"]
        text = json.dumps(schema, ensure_ascii=False)
        self.assertIn('"maxItems": 5', text)


if __name__ == "__main__":
    unittest.main()

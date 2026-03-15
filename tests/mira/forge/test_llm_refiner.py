from __future__ import annotations

from mira.forge_claude.question_gen.llm_refiner import _parse_llm_response


def test_parse_llm_response_accepts_json_with_trailing_text() -> None:
    text = """
Here you go.
```json
{
  "refined_questions": [
    {"id": "q1", "natural_language": "Show supplier records"}
  ]
}
```
Additional note that should be ignored.
"""

    payload = _parse_llm_response(text)

    assert payload["refined_questions"][0]["id"] == "q1"


def test_parse_llm_response_salvages_partial_refined_questions_array() -> None:
    text = """
{
  "refined_questions": [
    {"id": "q1", "natural_language": "Show supplier records"},
    {"id": "q2", "natural_language": "List part weights"},
    {"id": "q3", "natural_language": "Broken tail"
"""

    payload = _parse_llm_response(text)

    assert [item["id"] for item in payload["refined_questions"]] == ["q1", "q2"]

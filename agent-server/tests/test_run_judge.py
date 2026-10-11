"""The judge runner fails fast without spending a model call."""

import json

from server.run_judge import build_parser, main


def _description(path):
    path.write_text(json.dumps({
        "style": "layered",
        "components": [],
        "confidence": "low",
    }))


class TestJudgeRunner:
    def test_missing_root_is_exit_1(self, tmp_path):
        description = tmp_path / "description.json"
        _description(description)

        assert main([str(tmp_path / "ghost"), str(description)]) == 1

    def test_missing_description_is_exit_1(self, tmp_path):
        assert main([str(tmp_path), str(tmp_path / "ghost.json")]) == 1

    def test_invalid_description_is_exit_2(self, tmp_path):
        description = tmp_path / "description.json"
        description.write_text(json.dumps({"style": "layered", "confidence": "bogus"}))

        assert main([str(tmp_path), str(description)]) == 2

    def test_parser_defaults(self):
        args = build_parser().parse_args(["root", "description.json"])

        assert args.timeout == 300
        assert args.json is False
        assert args.quiet is False

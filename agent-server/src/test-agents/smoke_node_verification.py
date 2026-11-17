"""Real npm/Vitest/TSX smoke, no model, external network needed for dependencies."""

import json
import tempfile
from pathlib import Path

from server.runtimes.verification.templates import node_runtime


def main():
    output = Path("artifacts/testability-probe/node-toolchain-smoke")
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tallercito-node-smoke-") as temporary:
        root = Path(temporary)
        (root / "package.json").write_text('{"name":"smoke","version":"1.0.0","private":true}', encoding="utf-8")
        receipt = node_runtime.prepare(root)
        tests = root / ".tallercito/tests"
        tests.mkdir(parents=True)
        (tests / "react.test.tsx").write_text('''// @vitest-environment jsdom
import React from 'react';
import {test, expect} from 'vitest';
import {render, screen, cleanup} from '@testing-library/react';
test('real TSX rendering', () => {
  render(<button>Smoke</button>);
  expect(screen.getByRole('button').textContent).toBe('Smoke');
  cleanup();
});
''', encoding="utf-8")
        outcome = node_runtime.run(root, ".tallercito/tests/react.test.tsx")
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        (output / "outcome.json").write_text(json.dumps(outcome, indent=2), encoding="utf-8")
        print(receipt, outcome["classification"], outcome["detail"][:500], flush=True)
        if outcome["classification"] != "pass":
            raise RuntimeError("TSX smoke failed; inspect ignored artifact")


if __name__ == "__main__":
    main()

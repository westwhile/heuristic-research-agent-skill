"""Fixed P7C1 subprocess worker; stdin/stdout only, no Candidate loading."""

from __future__ import annotations

import base64
import json
import sys
import time


def main() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read())
        if set(payload) != {
            "arm",
            "axes_sha256",
            "case_input_sha256",
            "delay_ms",
            "exit_code",
            "output_base64",
        }:
            return 70
        if payload["arm"] not in {"baseline", "candidate"}:
            return 70
        delay_ms = payload["delay_ms"]
        exit_code = payload["exit_code"]
        if (
            isinstance(delay_ms, bool)
            or not isinstance(delay_ms, int)
            or delay_ms < 0
            or isinstance(exit_code, bool)
            or not isinstance(exit_code, int)
            or exit_code < 0
            or exit_code > 125
        ):
            return 70
        time.sleep(delay_ms / 1000)
        if exit_code:
            return exit_code
        output = base64.b64decode(payload["output_base64"], validate=True)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return 70
    sys.stdout.buffer.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

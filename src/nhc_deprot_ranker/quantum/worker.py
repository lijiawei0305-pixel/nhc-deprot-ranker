"""Internal fixed-attempt worker for the parent-supervised quantum runner.

The module imports no chemistry package.  Its ``main`` function repeats the
source-level gate as its first action, before inspecting arguments or requests.
Phase 8A deliberately leaves that gate closed.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from nhc_deprot_ranker.quantum import two_endpoint as runner


@dataclass(frozen=True)
class _WorkerArguments:
    request_path: Path
    output_root: Path
    attempt_id: str


def _parse_arguments(argv: Sequence[str] | None) -> _WorkerArguments:
    parser = argparse.ArgumentParser(
        prog="nhc-deprot-two-endpoint-worker",
        description="internal fixed-attempt worker; invoke only through the parent supervisor",
    )
    parser.add_argument("--request-path", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--attempt-id", required=True)
    parsed = parser.parse_args(argv)
    return _WorkerArguments(
        request_path=parsed.request_path,
        output_root=parsed.output_root,
        attempt_id=parsed.attempt_id,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Execute one guarded attempt; the authorization check must stay first."""

    runner._ensure_execution_authorized()  # pyright: ignore[reportPrivateUsage]
    arguments = _parse_arguments(argv)
    request = runner.load_two_endpoint_request(arguments.request_path)
    if request.execution_authorized is not True:
        raise runner.ExecutionNotAuthorizedError(
            "frozen request does not authorize worker execution"
        )
    runner._ensure_execution_authorized()  # pyright: ignore[reportPrivateUsage]
    try:
        runner._execute_validated_request(  # pyright: ignore[reportPrivateUsage]
            request,
            arguments.output_root,
            backend=runner.PySCFBackend(),
            attempt_id=arguments.attempt_id,
        )
    except runner.TwoEndpointRunError as error:
        return error.exit_code
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised only by the supervisor
    raise SystemExit(main())

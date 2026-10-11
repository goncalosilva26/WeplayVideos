"""Entry point: ``python -m behance_studio`` starts the desktop app;
``python -m behance_studio <command> ...`` runs the command-line interface."""

from __future__ import annotations

import sys


def main() -> int:
    from behance_studio.cli import COMMANDS

    if len(sys.argv) > 1 and sys.argv[1] in COMMANDS:
        from behance_studio.cli import main as cli_main

        return cli_main(sys.argv[1:])
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        from behance_studio.cli import build_parser

        build_parser().print_help()
        return 0
    from behance_studio.ui.app import run

    return run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())

"""Launch the Hermes setup wizard."""

from __future__ import annotations

import sys


def main() -> None:
    from hermes_wizard.gui.main_window import run

    sys.exit(run())


if __name__ == "__main__":
    main()

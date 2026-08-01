"""Entry point for ``python -m src``.

Parses command-line arguments, loads config, loads test cases, runs the
evaluation pipeline, and writes reports. Exits 0 if all metric thresholds
were met and 1 otherwise — suitable for gating CI/CD deployments.
"""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())

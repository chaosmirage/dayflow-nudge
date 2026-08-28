"""Run the daemon loop: ``python3 -m dayflow_nudge``.

The daemon module is imported inside the guard so that merely importing
the package or this shim never pulls in the daemon machinery; the entry
point stays this single delegation with no arguments of its own.
"""

import sys

if __name__ == "__main__":
    from dayflow_nudge import daemon

    sys.exit(daemon.main())

"""Console entry for the bundled, token-free Desktop IPC helper.

Unlike the windowed desktop executable, this companion has real stdout/stderr.
It uses the bundled interpreter, never a system Python or a model environment.
"""
from kiss_cli.agent_bridge import main

raise SystemExit(main())

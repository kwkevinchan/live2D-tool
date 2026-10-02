"""python Tools/wf <command> ... (or python -m wf with Tools on the path): see wf/cli.py."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wf.cli import main   # noqa: E402

sys.exit(main())

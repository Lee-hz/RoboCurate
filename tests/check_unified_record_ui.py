"""Compatibility entry point: both former review views now share one workspace."""
from pathlib import Path
import runpy
runpy.run_path(str(Path(__file__).with_name('check_single_audit_ui.py')),run_name='__main__')

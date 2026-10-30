"""Cloud and local-release entry point. Does not require an editable installation."""
from pathlib import Path
import sys
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / 'src'))
from homereach.explorer.release_ui import run_release_app
run_release_app(Path(__file__).resolve().parent / 'data')

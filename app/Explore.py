"""Launch the local real-data explorer; app/Home.py remains the synthetic demo."""
from pathlib import Path
from homereach.explorer.ui import run_app

run_app(Path(__file__).resolve().parents[1])

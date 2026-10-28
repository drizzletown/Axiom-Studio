"""Axiom Studio launch entrypoint. Requires Python 3.10+, lark.

  python run_studio.py
  python run_studio.py --port 8765 --no-browser
"""
import sys
from pathlib import Path
if sys.version_info<(3,10):raise SystemExit('Axiom Studio requires Python 3.10+')
try:
    import lark
except ImportError:
    raise SystemExit('Missing lark. Install dependencies: python -m pip install -r requirements.txt')
sys.path.insert(0,str(Path(__file__).resolve().parent/'studio'))
from server import main
if __name__=='__main__':main()

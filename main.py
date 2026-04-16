import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

from core.app import run

if __name__ == "__main__":
    run()
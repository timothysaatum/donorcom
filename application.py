import sys
import os

# Add 'app' directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

from main import app as application  # EB looks for variable 'application'

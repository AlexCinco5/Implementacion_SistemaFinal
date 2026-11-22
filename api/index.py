import os
import sys

# Permite importar backend/main.py desde la carpeta api/
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.main import app
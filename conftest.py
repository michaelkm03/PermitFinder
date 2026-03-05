"""
conftest.py — makes pytest discover the src/ package without sys.path hacks.
Place in project root. pytest will automatically add src/ to sys.path via
the testpaths + rootdir mechanism when the package is installed in editable mode.

If running tests WITHOUT `pip install -e .`, pytest uses this file to ensure
`import permit_engine` resolves correctly from the src/ layout.
"""
import sys
import os

# Insert src/ at the front of sys.path so `import permit_engine` always works,
# regardless of whether the package is installed or run directly.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

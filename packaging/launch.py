"""PyInstaller entry point - a script, so the package is imported as a package."""
import sys

from vjson_studio.app import main

sys.exit(main())

"""Entry point for running concierge as a module.

Allows running the application with:
    python -m concierge

This delegates to the Typer CLI app.
"""

from concierge.cli import app

if __name__ == "__main__":
    app()

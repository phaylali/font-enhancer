#!/usr/bin/env python3
"""
Font Enhancer - Main Entry Point

A Linux-native desktop application for automated font kerning with live preview.
Integrates with FontForge via UFO interchange format.

Usage:
    python main.py
    python main.py --font=/path/to/font.ufo/

Requirements:
    See requirements.txt

Author: Font Enhancer Team
License: MIT
"""

import sys
import logging
import argparse


def setup_logging():
    """Configure basic logging for the application."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Font Enhancer - Automated font kerning with live preview"
    )
    parser.add_argument(
        "--font", "-f", type=str, help="Path to UFO font directory to load on startup"
    )
    parser.add_argument(
        "--auto-kern",
        "-k",
        action="store_true",
        help="Automatically run auto-kern after loading font",
    )
    parser.add_argument(
        "--export",
        type=str,
        metavar="PATH",
        help="Export kerned font to PATH (UFO or OTF) and exit",
    )
    parser.add_argument("--preview", type=str, help="Test string to preview")
    return parser.parse_args()


def main():
    """Launch the Font Enhancer GUI application."""
    setup_logging()
    logger = logging.getLogger(__name__)
    args = parse_args()

    logger.info("Starting Font Enhancer...")

    try:
        from gui import main as gui_main

        gui_main(args)
    except ImportError as e:
        logger.error(f"Missing dependency: {e}")
        print(f"Error: Missing dependency {e}", file=sys.stderr)
        print(
            "Install dependencies with: pip install -r requirements.txt",
            file=sys.stderr,
        )
        sys.exit(1)
    except Exception as e:
        logger.exception("Failed to start application")
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

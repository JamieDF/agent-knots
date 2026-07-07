#!/usr/bin/env python3
"""Greeting script that prints a greeting and the current time."""

from datetime import datetime


def main():
    """Print greeting and current time."""
    print("Hello, World!")
    print(f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()

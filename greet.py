#!/usr/bin/env python3
"""A simple greeting script that prints a greeting and the current time."""

from datetime import datetime

def main():
    print("Hello! Welcome to the greeting script.")
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"The current time is: {current_time}")

if __name__ == "__main__":
    main()

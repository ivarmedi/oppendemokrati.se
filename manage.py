#!/usr/bin/env python
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    from django.core.management import execute_from_command_line

    argv = sys.argv
    if _should_use_port_env(argv):
        argv = argv + [os.environ["PORT"]]
    execute_from_command_line(argv)


def _should_use_port_env(argv):
    if len(argv) < 2 or argv[1] != "runserver":
        return False
    if "PORT" not in os.environ:
        return False
    return not any(arg.isdigit() or ":" in arg for arg in argv[2:] if not arg.startswith("-"))


if __name__ == "__main__":
    main()

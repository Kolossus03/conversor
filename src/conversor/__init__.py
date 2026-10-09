import sys


def main() -> int:
    if "--worker" in sys.argv[1:]:
        from .worker import main as worker_main

        return worker_main()
    from .app import run

    return run(sys.argv[1:])

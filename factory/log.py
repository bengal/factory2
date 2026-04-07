import sys
from datetime import datetime

RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[0;33m"
BLUE = "\033[0;34m"
BOLD = "\033[1m"
DIM = "\033[2m"
NC = "\033[0m"


def _ts():
    return datetime.now().strftime("%H:%M:%S")


def info(msg: str):
    print(f"{GREEN}[INFO]{NC} {_ts()} {msg}", file=sys.stderr, flush=True)


def warn(msg: str):
    print(f"{YELLOW}[WARN]{NC} {_ts()} {msg}", file=sys.stderr, flush=True)


def error(msg: str):
    print(f"{RED}[ERROR]{NC} {_ts()} {msg}", file=sys.stderr, flush=True)


def phase(msg: str):
    print(f"{BOLD}{BLUE}[PHASE]{NC} {_ts()} {msg}", file=sys.stderr, flush=True)

"""Small local shortcut client. No application imports or network listener."""

import socket
import sys


def send(path: str, action: str) -> None:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(2)
        client.connect(path)
        client.sendall(action.encode("ascii"))


if __name__ == "__main__":
    try:
        send(sys.argv[1], sys.argv[2])
    except (OSError, IndexError):
        sys.exit(1)

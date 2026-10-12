"""Run locally against the server's IMR_DB_PATH; never expose this as an HTTP API."""
import sys

from db import init_db
from fairness import rotate_key


if __name__ == '__main__':
    init_db()
    try:
        result = rotate_key()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    print('Previous key retired:', result['previous_hash'])
    print('Current server-key SHA-256:', result['current_hash'])

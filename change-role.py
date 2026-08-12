import argparse
import json
import os
import sys
import tempfile


USERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.json")
ROLES = ("owner", "editor", "viewer")
ALIASES = {"edit": "editor"}


def load_users():
    try:
        with open(USERS_FILE, encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError) as error:
        print(f"Cannot read users.json: {error}")
        sys.exit(1)


def save_users(users):
    directory = os.path.dirname(USERS_FILE)
    fd, temporary = tempfile.mkstemp(prefix=".tmp-users-", dir=directory, text=True)
    try:
        os.chmod(temporary, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(users, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, USERS_FILE)
        try:
            os.chmod(USERS_FILE, 0o600)
        except OSError:
            pass
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def main():
    parser = argparse.ArgumentParser(description="Change a file-server user's role.")
    parser.add_argument("username")
    parser.add_argument("role", choices=ROLES + tuple(ALIASES))
    arguments = parser.parse_args()
    role = ALIASES.get(arguments.role, arguments.role)

    users = load_users()
    record = users.get(arguments.username)
    if not isinstance(record, dict):
        print(f"User '{arguments.username}' does not exist.")
        sys.exit(1)

    current = record.get("role")
    other_owner_exists = any(
        name != arguments.username and isinstance(user, dict) and user.get("role") == "owner"
        for name, user in users.items()
    )
    if role != "owner" and not other_owner_exists:
        print("Cannot leave the server without an owner. Promote another account first.")
        sys.exit(1)

    record["role"] = role
    save_users(users)
    print(f"Changed '{arguments.username}' from {current or 'unassigned'} to {role}.")


if __name__ == "__main__":
    main()

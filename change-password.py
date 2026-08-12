import argparse
import json
import os
import secrets
import sys
import tempfile
import uuid

USERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.json")


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
    parser = argparse.ArgumentParser(description="Rotate a file-server user's password.")
    parser.add_argument("username", nargs="?", help="Account to update")
    arguments = parser.parse_args()
    username = arguments.username.strip() if arguments.username else input("Username: ").strip()

    users = load_users()
    record = users.get(username)
    if not isinstance(record, dict):
        print(f"User '{username}' does not exist.")
        sys.exit(1)

    password = str(uuid.uuid4())
    record["password"] = password
    record.pop("password_hash", None)
    record.pop("uuid", None)
    record["credential_version"] = secrets.token_hex(16)
    save_users(users)

    print()
    print(f"Password changed for '{username}'.")
    print(f"New password: {password}")
    print("All existing sessions for this account will be rejected.")
    print()


if __name__ == "__main__":
    main()

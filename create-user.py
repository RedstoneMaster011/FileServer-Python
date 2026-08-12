import argparse
import json
import os
import secrets
import sys
import tempfile
import uuid

USERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.json")
ROLES = ("owner", "editor", "viewer")
ROLE_ALIASES = {"edit": "editor"}


def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
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


def validate_username(username, users):
    if not username:
        return "Username cannot be empty."
    if len(username) > 64:
        return "Username must be 64 characters or fewer."
    if any(ord(character) < 32 for character in username):
        return "Username contains control characters."
    if any(character in username for character in ' /\\:*?"<>|'):
        return "Username contains invalid characters."
    if any(existing.casefold() == username.casefold() for existing in users):
        return f"User '{username}' already exists."
    return None


def create_user(username, role):
    users = load_users()
    role = ROLE_ALIASES.get(role, role)
    error = validate_username(username, users)
    if error:
        print(f"Error: {error}")
        sys.exit(1)

    if role not in ROLES:
        print(f"Error: role must be one of {', '.join(ROLES)}.")
        sys.exit(1)
    if not users:
        role = "owner"

    password = str(uuid.uuid4())
    users[username] = {
        "password": password,
        "role": role,
        "credential_version": secrets.token_hex(16),
    }
    save_users(users)

    print()
    print("User created!")
    print(f"  Username : {username}")
    print(f"  Role     : {role}")
    print(f"  Password : {password}")
    print()
    print("The password is currently stored in readable form in users.json.")
    print()


def choose_role(default):
    raw = input(f"Role [owner/editor/viewer] ({default}): ").strip().lower()
    return raw or default


def main():
    parser = argparse.ArgumentParser(description="Create a file-server user.")
    parser.add_argument("username", nargs="?", help="Username for the new account")
    parser.add_argument("--role", choices=ROLES + tuple(ROLE_ALIASES), help="Permission role")
    arguments = parser.parse_args()

    username = arguments.username.strip() if arguments.username else input("Username: ").strip()
    users = load_users()
    default_role = "owner" if not users else "viewer"
    role = arguments.role or choose_role(default_role)
    create_user(username, role)


if __name__ == "__main__":
    main()

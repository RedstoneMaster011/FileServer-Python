import os
import sys
import json
import uuid

USERS_FILE = os.path.join(os.path.dirname(__file__), "users.json")

def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE) as f:
        return json.load(f)

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)

def create_user(username):
    users = load_users()

    if username in users:
        print(f"❌  User '{username}' already exists in users.json")
        sys.exit(1)

    uid = str(uuid.uuid4())
    users[username] = {"uuid": uid}
    save_users(users)

    print()
    print("✅  User created!")
    print(f"    Username : {username}")
    print(f"    UUID pass: {uid}")
    print()
    print("  → Sign in at /login using this UUID as the password.")
    print("  → Keep it safe — it won't be shown again.")
    print()

def main():
    if len(sys.argv) >= 2:
        username = sys.argv[1].strip()
    else:
        username = input("Enter username: ").strip()

    if not username:
        print("❌  Username cannot be empty.")
        sys.exit(1)

    if any(c in username for c in ' /\\:*?"<>|'):
        print("❌  Username contains invalid characters.")
        sys.exit(1)

    create_user(username)

if __name__ == "__main__":
    main()

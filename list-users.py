import json
import os
import sys


USERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.json")


def main():
    try:
        with open(USERS_FILE, encoding="utf-8") as handle:
            users = json.load(handle)
    except FileNotFoundError:
        print("No users have been created yet.")
        return
    except (OSError, json.JSONDecodeError) as error:
        print(f"Cannot read users.json: {error}")
        sys.exit(1)

    if not isinstance(users, dict) or not users:
        print("No users have been created yet.")
        return

    width = max(len("Username"), *(len(str(username)) for username in users))
    print(f"{'Username':<{width}}  Role     Password")
    print(f"{'-' * width}  --------  ------------------------------------")
    for username, record in users.items():
        role = record.get("role", "legacy/unassigned") if isinstance(record, dict) else "invalid"
        password = record.get("password", record.get("uuid", "unavailable")) if isinstance(record, dict) else "unavailable"
        print(f"{username:<{width}}  {role:<8}  {password}")
    print("\nKeep this output private. Anyone with a listed password can sign in.")


if __name__ == "__main__":
    main()

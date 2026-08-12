import os
import sys
import json
import tempfile

NAME_FILE = os.path.join(os.path.dirname(__file__), "name.json")

def load_name():
    if not os.path.exists(NAME_FILE):
        return "Drive"
    with open(NAME_FILE) as f:
        return json.load(f).get("name", "Drive")

def save_name(name):
    directory = os.path.dirname(NAME_FILE)
    fd, temporary = tempfile.mkstemp(prefix=".tmp-name-", dir=directory, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"name": name}, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, NAME_FILE)
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
    current = load_name()
    print(f"  Current name: {current}")

    if len(sys.argv) >= 2:
        name = sys.argv[1].strip()
    else:
        name = input("Enter new app name: ").strip()

    if not name:
        print("   Name cannot be empty.")
        sys.exit(1)
    if len(name) > 80 or any(ord(character) < 32 for character in name):
        print("   Name must be 80 characters or fewer and cannot contain control characters.")
        sys.exit(1)

    save_name(name)

    print()
    print("✅  Name updated!")
    print(f"    Name: {name}")
    print()
    print("  → Restart the server for changes to take effect.")
    print()

if __name__ == "__main__":
    main()

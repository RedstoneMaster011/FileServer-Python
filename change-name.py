import os
import sys
import json

NAME_FILE = os.path.join(os.path.dirname(__file__), "name.json")

def load_name():
    if not os.path.exists(NAME_FILE):
        return "Drive"
    with open(NAME_FILE) as f:
        return json.load(f).get("name", "Drive")

def save_name(name):
    with open(NAME_FILE, "w") as f:
        json.dump({"name": name}, f, indent=2)

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

    save_name(name)

    print()
    print("✅  Name updated!")
    print(f"    Name: {name}")
    print()
    print("  → Restart the server for changes to take effect.")
    print()

if __name__ == "__main__":
    main()

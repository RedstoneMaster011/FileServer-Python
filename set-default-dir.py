import os
import sys
import json

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE) as f:
        return json.load(f)

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

def main():
    if len(sys.argv) >= 2:
        directory = sys.argv[1].strip()
    else:
        current = load_config().get("root_dir", "")
        if current:
            print(f"  Current root: {current}")
        directory = input("Enter root directory path: ").strip()

    directory = os.path.realpath(os.path.expanduser(directory))

    if not os.path.exists(directory):
        create = input(f"  '{directory}' doesn't exist. Create it? [y/N] ").strip().lower()
        if create == "y":
            os.makedirs(directory, exist_ok=True)
            print(f"  📁 Created: {directory}")
        else:
            print("   Aborted.")
            sys.exit(1)

    if not os.path.isdir(directory):
        print(f"   '{directory}' is not a directory.")
        sys.exit(1)

    if len(sys.argv) >= 3:
        try:
            port = int(sys.argv[2])
        except ValueError:
            print("   Port must be a number.")
            sys.exit(1)
    else:
        cfg = load_config()
        current_port = cfg.get("port", 5000)
        raw = input(f"Enter port [{current_port}]: ").strip()
        port = int(raw) if raw else current_port

    cfg = load_config()
    cfg["root_dir"] = directory
    cfg["port"] = port
    save_config(cfg)

    print()
    print("✅  Config saved!")
    print(f"    Root : {directory}")
    print(f"    Port : {port}")
    print()
    print("    Run the server with just:  python main.py")
    print()

if __name__ == "__main__":
    main()

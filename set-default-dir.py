import os
import sys
import json
import tempfile

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE) as f:
        return json.load(f)

def save_config(cfg):
    directory = os.path.dirname(CONFIG_FILE)
    fd, temporary = tempfile.mkstemp(prefix=".tmp-config-", dir=directory, text=True)
    try:
        os.chmod(temporary, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, CONFIG_FILE)
        try:
            os.chmod(CONFIG_FILE, 0o600)
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

    project_dir = os.path.realpath(os.path.dirname(__file__))
    if os.path.commonpath([directory, project_dir]) == directory:
        print("   The storage root cannot contain the file-server application.")
        print("   Choose a dedicated data folder, such as this project's 'files' folder.")
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

    if not 1 <= port <= 65535:
        print("   Port must be between 1 and 65535.")
        sys.exit(1)

    cfg = load_config()
    cfg["root_dir"] = directory
    cfg["port"] = port
    cfg.setdefault("bind_host", "0.0.0.0")
    cfg.setdefault("max_upload_bytes", 20 * 1024 * 1024 * 1024)
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

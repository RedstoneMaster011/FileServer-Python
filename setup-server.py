import os
import sys
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def run(script):
    subprocess.run([sys.executable, os.path.join(BASE_DIR, script)], check=False)

def main():
    print()
    print("  Setup")
    print("  ═══════════════════════════════════════════")
    print()

    print("── Step 1: App Name ──────────────────────────")
    run("change-name.py")

    print("── Step 2: Root Directory ────────────────────")
    run("set-default-dir.py")

    print("── Step 3: Create User ───────────────────────")
    run("create-user.py")

    print("═══════════════════════════════════════════")
    print("  ✅ Setup complete! Run the server with:")
    print("     python main.py")
    print()

if __name__ == "__main__":
    main()
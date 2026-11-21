"""Build the browser version of the client with pygbag.

    python build_web.py

Copies the client files into build/web_stage/proximitywars, runs pygbag on
them and puts the result in web_dist/. The server (server.py) serves
web_dist/ at /play, so the game is one link on the same host as the
WebSocket. Render runs this as part of the build command.
"""

import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
STAGE = os.path.join(ROOT, "build", "web_stage", "proximitywars")
DIST = os.path.join(ROOT, "web_dist")

CLIENT_FILES = [
    "main.py", "ui.py", "webglue.py", "game.py", "sprites.py", "setup_screen.py", "feedback_screen.py",
    "rules.py", "engine.py", "bot.py", "session.py", "metrics.py", "local_peer.py",
]
CLIENT_DIRS = ["assets", "examples"]


def main():
    shutil.rmtree(os.path.join(ROOT, "build", "web_stage"), ignore_errors=True)
    os.makedirs(STAGE)
    for name in CLIENT_FILES:
        shutil.copy2(os.path.join(ROOT, name), STAGE)
    for name in CLIENT_DIRS:
        shutil.copytree(os.path.join(ROOT, name), os.path.join(STAGE, name))

    cmd = [sys.executable, "-m", "pygbag", "--build", "--no_opt", "--ume_block", "0",
           "--title", "Proximity Wars", "--app_name", "proximitywars", STAGE]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=os.path.dirname(STAGE))

    built = os.path.join(STAGE, "build", "web")
    shutil.rmtree(DIST, ignore_errors=True)
    shutil.copytree(built, DIST)
    print("Web build ready in", DIST)
    for name in sorted(os.listdir(DIST)):
        print("  ", name, os.path.getsize(os.path.join(DIST, name)), "bytes")


if __name__ == "__main__":
    main()

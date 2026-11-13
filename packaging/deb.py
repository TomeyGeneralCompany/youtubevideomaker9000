"""Build a Debian desktop package. Requires dpkg-deb."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
FILES = ("studio.html", "local_studio.py", "run_mavis.py", "configure_media.py",
         "requirements.txt", ".env.example", "examples/channel-settings.json",
         "examples/media-profile.json", "examples/voice-profile.json",
         "voice-runtime/model-files.json", "voice-runtime/LICENSE-engine.txt")

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('target', type=Path)
parser.add_argument('--billing-url', default='')
args = parser.parse_args()
if args.billing_url:
    url = urlsplit(args.billing_url)
    if url.scheme != 'https' or not url.hostname or url.username or url.query or url.fragment:
        parser.error('Use the HTTPS base URL of the billing service.')
args.target.parent.mkdir(parents=True, exist_ok=True)
with TemporaryDirectory() as directory:
    root = Path(directory)
    app = root / 'usr/share/mavis'
    for name in (*FILES, *(str(p.relative_to(ROOT)) for p in (ROOT / 'mavis').glob('*.py'))):
        target = app / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    (app / 'subscription.json').write_text(json.dumps({'required': True, 'url': args.billing_url}))
    for source, target, mode in (
        ('debian-launch.sh', 'usr/bin/mavis', 0o755),
        ('icon.svg', 'usr/share/icons/hicolor/scalable/apps/mavis.svg', 0o644),
        ('mavis.desktop', 'usr/share/applications/mavis.desktop', 0o644),
    ):
        dest = root / target
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / 'packaging' / source, dest)
        dest.chmod(mode)
    (root / 'DEBIAN').mkdir()
    (root / 'DEBIAN/control').write_text(
        'Package: mavis\nVersion: 0.1.0\nArchitecture: all\n'
        'Maintainer: Tomey General Company LLC\n'
        'Depends: python3, python3-venv, ffmpeg, xdg-utils, util-linux\n'
        'Description: MAVIS local video production studio\n')
    subprocess.run(['dpkg-deb', '--root-owner-group', '--build', directory, str(args.target)], check=True)

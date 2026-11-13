"""Build a Linux installer ZIP from a clean allowlist of release files."""
import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
FILES = ('studio.html', 'local_studio.py', 'run_mavis.py', 'configure_media.py',
         'requirements.txt', '.env.example', 'examples/channel-settings.json',
         'examples/media-profile.json', 'examples/voice-profile.json',
         'voice-runtime/model-files.json', 'voice-runtime/LICENSE-engine.txt')


def build(target):
    target.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(target, 'w', ZIP_DEFLATED) as package:
        for name in (*FILES, *(str(p.relative_to(ROOT)) for p in sorted((ROOT / 'mavis').glob('*.py')))):
            package.write(ROOT / name, f'MAVIS/app/{name}')
        for name in ('install.sh', 'launch.sh', 'billing.env', 'INSTALL.txt'):
            package.write(ROOT / 'packaging' / name, f'MAVIS/{name}')
        package.write(ROOT / 'packaging/icon.svg', 'MAVIS/app/icon.svg')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target', type=Path)
    build(parser.parse_args().target)

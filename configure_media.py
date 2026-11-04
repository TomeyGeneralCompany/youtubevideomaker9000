"""Configure selected media assets in a separate workspace; never change a live installation."""
import argparse, hashlib, json, shutil
from pathlib import Path

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace', required=True, type=Path)
    p.add_argument('--assets-dir', required=True, type=Path)
    p.add_argument('--voice-profile', required=True, type=Path)
    p.add_argument('--background', type=Path)
    p.add_argument('--brand', default='')
    a = p.parse_args()
    root = a.workspace.expanduser().resolve()
    assets = a.assets_dir.expanduser().resolve()
    required = ['poses.png', 'walk-cycle.png', 'walk-cycle.json', 'puff-cycle.png']
    missing = [name for name in required if not (assets / name).is_file()]
    if missing:
        p.error('Animation pack is missing: ' + ', '.join(missing))
    voice = json.loads(a.voice_profile.read_text())
    if voice.get('provider') == 'qwen-local':
        if not voice.get('reference_text') or not (voice.get('instruction') or voice.get('reference_wav')):
            p.error('Local voice requires reference_text plus instruction or reference_wav.')
        if voice.get('reference_wav'):
            ref = Path(voice['reference_wav']).expanduser()
            if not ref.is_absolute():
                ref = a.voice_profile.resolve().parent / ref
            if not ref.is_file():
                p.error('Voice reference file does not exist.')
            voice['reference_wav'] = str(ref.resolve())
    else:
        p.error('Voice provider must be qwen-local; the unused Edge/gTTS path has been removed.')
    if a.background and (not a.background.is_file()):
        p.error('Background file does not exist.')
    root.mkdir(parents=True, exist_ok=True)
    for name in ['media-profile.json', 'voice-profile.json']:
        if (root / name).exists():
            p.error(name + ' already exists; choose a new workspace or edit the existing profile explicitly.')
    target = root / 'assets/animation'
    target.mkdir(parents=True, exist_ok=True)
    for name in required:
        shutil.copy2(assets / name, target / name)
    manifest = {name: hashlib.sha256((target / name).read_bytes()).hexdigest() for name in required}
    (target / 'approved-animation-sha256.json').write_text(json.dumps(manifest, indent=2))
    profile = {'brand_name': a.brand, 'animation': {'assets_dir': 'assets/animation', 'background_color': '#ffffff'}}
    if a.background:
        profile['animation']['background'] = str(a.background.resolve())
    (root / 'media-profile.json').write_text(json.dumps(profile, indent=2))
    (root / 'voice-profile.json').write_text(json.dumps(voice, indent=2))
    print('Media profiles saved to', root)
    print('Set TUBE_WORKSPACE to this folder. No publishing or scheduled services were changed.')
if __name__ == '__main__':
    main()

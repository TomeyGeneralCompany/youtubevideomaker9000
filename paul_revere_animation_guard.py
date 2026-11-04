"""Validate the selected complete-cel animation asset pack."""

def verify_approved_animation():
    import hashlib, json
    from moduli.runtime_profile import animation_directory
    root = animation_directory()
    required = ['poses.png', 'walk-cycle.png', 'walk-cycle.json', 'puff-cycle.png']
    for name in required:
        if not (root / name).is_file():
            raise RuntimeError('Selected animation pack is missing ' + name)
    path = root / 'approved-animation-sha256.json'
    if not path.is_file():
        raise RuntimeError('Selected animation pack needs approved-animation-sha256.json.')
    data = json.loads(path.read_text())
    for name, digest in data.items():
        p = (root / name).resolve()
        if not p.is_relative_to(root.resolve()) or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != digest:
            raise RuntimeError('Selected animation asset failed verification: ' + name)

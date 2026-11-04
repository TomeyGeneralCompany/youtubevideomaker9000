"""Reference-free voice design once, cached local narration in the saved voice."""
from pathlib import Path
import hashlib, json, subprocess, os, tempfile, time, wave
HOME = Path.home()
ROOT = Path(os.environ.get('TUBE_WORKSPACE', HOME / '.tomey-media'))
ENGINE = Path(os.environ.get('VOICE_ENGINE_DIR', HOME / '.local/share/tomey-media-voice')).expanduser()
MODELS = ENGINE / 'models'
DESIGN = 'qwen-talker-1.7b-voicedesign-Q4_K_M.gguf'
BASE = 'qwen-talker-0.6b-base-Q4_K_M.gguf'
CODEC = 'qwen-tokenizer-12hz-Q8_0.gguf'

def profile():
    from moduli.runtime_profile import voice_profile
    p = voice_profile()
    if not str(p.get('reference_text', '')).strip():
        raise ValueError('Voice profile requires reference_text.')
    if not p.get('reference_wav') and (not str(p.get('instruction', '')).strip()):
        raise ValueError('Supply a voice design instruction or reference_wav.')
    return p

def run(command, text):
    print('[Local voice] Local CPU synthesis; this may take several minutes.', flush=True)
    with tempfile.TemporaryFile() as errors:
        p = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=errors, stdout=errors)
        p.stdin.write(text.encode())
        p.stdin.close()
        started = time.monotonic()
        while p.poll() is None:
            if time.monotonic() - started > 7200:
                p.kill()
                p.wait()
                raise RuntimeError('Local TTS exceeded two-hour timeout')
            time.sleep(15)
            if p.poll() is None:
                print('[Local voice] Still generating locally...', flush=True)
        if p.returncode:
            errors.seek(0)
            raise RuntimeError(errors.read().decode(errors='replace')[-3000:])

def validate_wav(path):
    import wave
    with wave.open(str(path)) as w:
        seconds = w.getnframes() / w.getframerate()
        if seconds < 0.5:
            raise RuntimeError('Local voice produced no usable audio')
        if w.getsampwidth() == 2:
            import array
            samples = array.array('h')
            samples.frombytes(w.readframes(w.getnframes()))
            if not samples or max((abs(v) for v in samples)) < 32:
                raise RuntimeError('Local voice produced silence')
    return seconds

def design():
    p = profile()
    key = hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest()[:16]
    folder = ROOT / 'assets/animation/voices' / key
    folder.mkdir(parents=True, exist_ok=True)
    ref = folder / 'reference.wav'
    text = folder / 'reference.txt'
    if ref.exists():
        try:
            validate_wav(ref)
            text.write_text(p['reference_text'])
            return (ref, text)
        except (RuntimeError, OSError, wave.Error, EOFError):
            ref.unlink(missing_ok=True)
    text.write_text(p['reference_text'])
    selected = p.get('reference_wav')
    if selected:
        import shutil
        source = Path(selected).expanduser()
        if not source.is_absolute():
            source = ROOT / source
        shutil.copyfile(source, ref)
        validate_wav(ref)
        return (ref, text)
    tmp = folder / 'reference.partial.wav'
    run([str(ENGINE / 'source/build/qwen-tts'), '--model', str(MODELS / DESIGN), '--codec', str(MODELS / CODEC), '--lang', 'English', '--instruct', p['instruction'], '--seed', str(p.get('seed', 42)), '--max-new', '600', '-o', str(tmp)], p['reference_text'])
    validate_wav(tmp)
    tmp.replace(ref)
    return (ref, text)

def synthesize(text, output):
    ref, transcript = design()
    p = profile()
    signature = hashlib.sha256(ref.read_bytes() + text.encode() + json.dumps(p, sort_keys=True).encode()).hexdigest()
    cache = ROOT / 'cache/voice'
    cache.mkdir(parents=True, exist_ok=True)
    wav = cache / (signature + '.wav')
    if wav.exists():
        try:
            validate_wav(wav)
        except (RuntimeError, OSError, wave.Error, EOFError):
            wav.unlink(missing_ok=True)
    if not wav.exists():
        tmp = cache / (signature + '.partial.wav')
        run([str(ENGINE / 'source/build/qwen-tts'), '--model', str(MODELS / BASE), '--codec', str(MODELS / CODEC), '--lang', 'English', '--ref-wav', str(ref), '--ref-text', str(transcript), '--seed', str(p.get('seed', 42)), '--max-new', str(max(600, len(text.split()) * 14)), '-o', str(tmp)], text)
        validate_wav(tmp)
        tmp.replace(wav)
    validate_wav(wav)
    from moduli.ffmpeg_utils import ffmpeg_path
    dest = Path(output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([ffmpeg_path(), '-y', '-v', 'error', '-threads', '2', '-filter_threads', '1', '-i', str(wav), '-af', 'loudnorm=I=-14:TP=-1.5:LRA=11', '-ar', '48000', '-ac', '2', '-c:a', 'libmp3lame', '-b:a', '192k', str(dest)], check=True, capture_output=True, timeout=180)
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['design', 'preview'])
    args = parser.parse_args()
    if args.command == 'design':
        print('Designed voice:', design()[0])
    else:
        dest = ROOT / 'voice-preview.mp3'
        synthesize('This is a preview of the voice selected for this project.', dest)
        print('Preview:', dest)

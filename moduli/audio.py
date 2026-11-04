import os
import shutil
import subprocess
import sys
import tempfile
from moduli.ffmpeg_utils import ffmpeg_path as _ffmpeg
VOICE_DEFAULT = ''
TTS_TIMEOUT = 45
CHUNK_WORDS = 300

def _split_chunks(text: str, max_words: int=CHUNK_WORDS) -> list[str]:
    sentences = text.replace('\n', ' ').split('. ')
    chunks, current, count = ([], [], 0)
    for s in sentences:
        parole = s.split()
        pezzi = [' '.join(parole[i:i + max_words]) for i in range(0, len(parole), max_words)] if len(parole) > max_words else [s]
        for pezzo in pezzi:
            w = len(pezzo.split())
            if count + w > max_words and current:
                chunks.append('. '.join(current) + '.')
                current, count = ([], 0)
            current.append(pezzo)
            count += w
    if current:
        chunks.append('. '.join(current))
    return [c for c in chunks if c.strip(' .')]

def _tts_worker(text: str, output_path: str, voice: str) -> None:
    import asyncio
    import edge_tts

    async def _run():
        profile = _voice_profile()
        communicate = edge_tts.Communicate(text, voice, rate=profile.get('rate', '+0%'), pitch=profile.get('pitch', '+0Hz'))
        await asyncio.wait_for(communicate.save(output_path), timeout=TTS_TIMEOUT - 5)
    asyncio.run(_run())
_RADICE_PROGETTO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _edge_tts_chunk(text: str, output_path: str, voice: str) -> bool:
    proc = subprocess.Popen([sys.executable, '-c', f'import sys; sys.path.insert(0, {_RADICE_PROGETTO!r});from moduli.audio import _tts_worker;_tts_worker({text!r}, {output_path!r}, {voice!r})'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
    try:
        _, stderr = proc.communicate(timeout=TTS_TIMEOUT)
        if proc.returncode == 0:
            return True
        err = stderr.decode(errors='replace').strip()
        print(f'[TTS] Edge TTS chunk error: {err}', flush=True)
        return False
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        print(f'[TTS] Edge TTS TIMEOUT {TTS_TIMEOUT}s for chunk', flush=True)
        return False

def _concat_audio(parts: list[str], output_path: str) -> None:
    if len(parts) == 1:
        shutil.move(parts[0], output_path)
        return
    list_file = output_path + '.list.txt'
    try:
        ff = _ffmpeg()
        with open(list_file, 'w', encoding='utf-8') as f:
            for p in parts:
                f.write(f"file '{os.path.abspath(p)}'\n")
        subprocess.run([ff, '-y', '-f', 'concat', '-safe', '0', '-i', list_file, '-c', 'copy', output_path], check=True, capture_output=True)
        return
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        raise RuntimeError(f'Cannot join audio chunks: FFmpeg is unavailable or concatenation failed. Install FFmpeg and add it to PATH, or set FFMPEG_PATH in .env. Details: {e}') from e
    finally:
        try:
            os.remove(list_file)
        except OSError:
            pass

def _edge_tts(text: str, output_path: str, voice: str) -> bool:
    chunks = _split_chunks(text)
    print(f'[TTS] Edge TTS — voice: {voice} — {len(chunks)} chunks of approximately {CHUNK_WORDS} words', flush=True)
    tmp_parts = []
    try:
        for i, chunk in enumerate(chunks):
            tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=f'_chunk{i}.mp3')
            tmp = tmp_file.name
            tmp_file.close()
            tmp_parts.append(tmp)
            ok = False
            for attempt in range(2):
                print(f'[TTS]   chunk {i + 1}/{len(chunks)} attempt {attempt + 1}/2...', flush=True)
                if _edge_tts_chunk(chunk, tmp, voice):
                    ok = True
                    break
            if not ok:
                print(f'[TTS]   chunk {i + 1} failed permanently', flush=True)
                return False
        _concat_audio(tmp_parts, output_path)
        return True
    finally:
        for p in tmp_parts:
            if os.path.exists(p) and p != output_path:
                os.remove(p)

def _gtts(text: str, output_path: str, lang: str='en') -> bool:
    try:
        from gtts import gTTS
        print(f'[TTS] Using gTTS (Google) as fallback — language: {lang}...', flush=True)
        tts = gTTS(text=text, lang=lang, slow=False)
        tts.save(output_path)
        return True
    except Exception as e:
        print(f'[TTS] gTTS error: {e}', flush=True)
        return False

def _voice_profile():
    from moduli.runtime_profile import voice_profile
    return voice_profile()

def _load_voice():
    profile = _voice_profile()
    voice = str(profile.get('voice', '')).strip()
    if not voice:
        raise ValueError('Select an Edge TTS voice in voice-profile.json; no speaker is bundled or selected automatically.')
    return voice

def _gtts_lang(voice: str) -> str:
    """Extract a language code from an Edge TTS voice name, for example en-US-GuyNeural to en."""
    parts = voice.split('-')
    return parts[0] if parts else 'en'

def _audio_valido(output_path: str, parole: int) -> bool:
    """Reject missing, empty or implausibly short narration before editing begins."""
    try:
        if os.path.getsize(output_path) < 1024:
            return False
    except OSError:
        return False
    try:
        from moduli.montaggio import _media_duration
        durata = _media_duration(output_path)
    except Exception:
        return True
    attesa = parole / 130 * 60
    if attesa > 5 and durata < attesa * 0.4:
        print(f'[TTS] Suspicious audio: {durata:.0f}s for {parole} words (expected approximately {attesa:.0f}s)', flush=True)
        return False
    return True
LOUDNESS_TARGET_LUFS = os.environ.get('AUDIO_LUFS', '-14')
NORM_SAMPLE_RATE = os.environ.get('AUDIO_SAMPLE_RATE', '48000')
NORM_CHANNELS = os.environ.get('AUDIO_CHANNELS', '2')
NORM_BITRATE = os.environ.get('AUDIO_BITRATE', '192k')

def _normalizza(path: str) -> None:
    """Normalize narration loudness and export stereo audio at 48 kHz. Preserve the original audio if normalization fails."""
    tmp = path + '.norm.mp3'
    try:
        subprocess.run([_ffmpeg(), '-y', '-nostdin', '-v', 'error', '-i', path, '-af', f'loudnorm=I={LOUDNESS_TARGET_LUFS}:TP=-1.5:LRA=11', '-ar', NORM_SAMPLE_RATE, '-ac', NORM_CHANNELS, '-b:a', NORM_BITRATE, tmp], check=True, capture_output=True, stdin=subprocess.DEVNULL, timeout=600)
        os.replace(tmp, path)
        print(f'[TTS] Volume normalized to {LOUDNESS_TARGET_LUFS} LUFS ({NORM_SAMPLE_RATE} Hz, {NORM_CHANNELS} channels)', flush=True)
    except Exception as e:
        print(f'[TTS] Normalization skipped ({e}) — original audio', flush=True)
        try:
            os.remove(tmp)
        except OSError:
            pass

def genera_audio(text: str, output_path: str) -> None:
    if _voice_profile().get('provider') == 'qwen-local':
        from moduli.local_voice import synthesize
        synthesize(text, output_path)
        return
    voice = _load_voice()
    words = len(text.split())
    print(f'[TTS] Starting Edge TTS — voice: {voice} ({words} words)...', flush=True)
    if _edge_tts(text, output_path, voice) and _audio_valido(output_path, words):
        _normalizza(output_path)
        print(f'[TTS] Audio saved: {output_path}', flush=True)
        return
    if _voice_profile():
        raise RuntimeError('Selected mascot voice failed after Edge TTS retries; preserving voice instead of silently substituting gTTS')
    print('[TTS] Edge TTS failed — trying gTTS...', flush=True)
    if _gtts(text, output_path, lang=_gtts_lang(voice)) and _audio_valido(output_path, words):
        _normalizza(output_path)
        print(f'[TTS] Audio saved (gTTS): {output_path}', flush=True)
        return
    raise RuntimeError('TTS failed: neither Edge TTS nor gTTS produced usable audio')

"""Narration adapter for the installed local Qwen voice engine."""

def genera_audio(text, output_path):
    from moduli.local_voice import synthesize
    synthesize(text, output_path)
generate_audio = genera_audio

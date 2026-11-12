"""Narration adapter for the installed local Qwen voice engine."""

def generate_audio(text, output_path):
    from mavis.local_voice import synthesize
    synthesize(text, output_path)

"""Shared clip-source settings for first-run setup and the interface. Write credentials only to workspace .env, never to video preferences or logs."""
import os
from pathlib import Path
from moduli.video_ai import PROVIDER_DEFAULTS
SORGENTI = {'1': {'id': 'pexels', 'nome': 'Pexels (stock, free)', 'desc': 'Real clips downloaded from Pexels. No cost or additional API key.'}, '2': {'id': 'hybrid', 'nome': 'Hybrid (recommended)', 'desc': 'AI generates the opening clips; Pexels supplies the rest.'}, '3': {'id': 'ai', 'nome': 'AI only', 'desc': 'Every clip is AI generated. Closest match to the script, at a higher cost.'}}

def _env_file(workspace: str | Path='.') -> Path:
    return Path(workspace) / '.env'

def leggi_env(workspace: str | Path='.') -> dict:
    from dotenv import dotenv_values
    percorso = _env_file(workspace)
    return dict(dotenv_values(percorso)) if percorso.exists() else {}

def scrivi_env(workspace: str | Path, chiave: str, valore: str) -> None:
    from dotenv import set_key
    percorso = _env_file(workspace)
    percorso.touch(exist_ok=True)
    set_key(str(percorso), chiave, valore, quote_mode='never')
    os.environ[chiave] = valore

def stato(workspace: str | Path='.') -> str:
    """Return a readable settings summary for the status command."""
    env = leggi_env(workspace)
    sorgente = (env.get('VIDEO_SOURCE') or 'pexels').strip().lower()
    if sorgente not in {s['id'] for s in SORGENTI.values()}:
        sorgente = 'pexels'
    if sorgente == 'pexels':
        return 'Pexels (stock)'
    prov = (env.get('VIDEO_AI_PROVIDER') or 'replicate').strip().lower()
    conf = PROVIDER_DEFAULTS.get(prov, PROVIDER_DEFAULTS['replicate'])
    modello = (env.get('VIDEO_AI_MODEL') or '').strip() or conf['modello']
    chiave = '✓' if (env.get(conf['env_key']) or '').strip() else '✗ API key missing'
    etichetta = 'AI only' if sorgente == 'ai' else f"hybrid (max {env.get('VIDEO_AI_MAX_CLIPS', '6')} clip AI)"
    return f"{etichetta} — {conf['etichetta']} / {modello} [{chiave}]"

def _prova_generazione(console) -> None:
    """Generate one real clip to verify the provider key and model. Ask before spending provider credit and report the expected wait."""
    from moduli import video_ai
    console.print()
    console.print('  [dim]This test generates ONE real clip. It uses provider credits and can take 1–3 minutes.[/]')
    from rich.prompt import Confirm
    if not Confirm.ask('  Try it now?', default=False):
        return
    console.print()
    try:
        from rich.progress import Progress, SpinnerColumn, TextColumn
        with Progress(SpinnerColumn(), TextColumn('[cyan]Generation in progress...'), transient=True) as p:
            p.add_task('')
            percorso = video_ai.genera_clip('futuristic laboratory close up', durata=5)
        dimensione = os.path.getsize(percorso) / 1024 ** 2
        console.print(f'  [bold green]✓[/]  Clip generated: {percorso} ({dimensione:.1f} MB)')
    except Exception as e:
        console.print(f'  [bold red]✗[/]  {e}')
        console.print('  [dim]Check the API key and model name. The pipeline would fall back to Pexels.[/]')

def configura(console, workspace: str | Path='.', intestazione=None) -> str:
    """Show the interactive source menu and return the selected source."""
    from rich.prompt import Prompt
    env = leggi_env(workspace)
    if intestazione:
        intestazione()
    attuale = (env.get('VIDEO_SOURCE') or 'pexels').strip().lower()
    console.print('  [bold]Video clip source:[/]\n')
    for num, s in SORGENTI.items():
        segno = '[bold green]•[/]' if s['id'] == attuale else ' '
        console.print(f"  {segno} [cyan]{num}[/]  [bold]{s['nome']}[/]")
        console.print(f"       [dim]{s['desc']}[/]")
    console.print()
    default = next((n for n, s in SORGENTI.items() if s['id'] == attuale), '1')
    scelta = Prompt.ask('  Choose', choices=list(SORGENTI), default=default)
    sorgente = SORGENTI[scelta]['id']
    scrivi_env(workspace, 'VIDEO_SOURCE', sorgente)
    if sorgente == 'pexels':
        console.print()
        console.print('  [bold green]✓[/]  Pexels stock clips — no additional API key.')
        return sorgente
    console.print()
    console.print('  [bold]Video generation service:[/]\n')
    elenco = list(PROVIDER_DEFAULTS.items())
    for i, (pid, conf) in enumerate(elenco, start=1):
        console.print(f"  [cyan]{i}[/]  [bold]{conf['etichetta']}[/]  [dim]— default model: {conf['modello']}[/]")
        if conf.get('nota'):
            console.print(f"       [dim]{conf['nota']}[/]")
        gia = '  [green](API key already configured)[/]' if (env.get(conf['env_key']) or '').strip() else ''
        console.print(f"       [dim]API key: {conf['env_key']} — {conf['hint']}[/]{gia}")
    console.print()
    attuale_prov = (env.get('VIDEO_AI_PROVIDER') or 'replicate').strip().lower()
    default_prov = next((str(i) for i, (pid, _) in enumerate(elenco, start=1) if pid == attuale_prov), '1')
    idx = Prompt.ask('  Choose', choices=[str(i) for i in range(1, len(elenco) + 1)], default=default_prov)
    provider_id, conf = elenco[int(idx) - 1]
    scrivi_env(workspace, 'VIDEO_AI_PROVIDER', provider_id)
    if provider_id == 'pollinations':
        console.print()
        console.print('  [bold green]✓[/]  Pollinations does not require an API key.')
    else:
        console.print()
        esistente = (env.get(conf['env_key']) or '').strip()
        if esistente:
            console.print(f"  [dim]API key {conf['env_key']} already configured (...{esistente[-4:]}). Press Enter to keep it.[/]")
        else:
            console.print(f"  [dim cyan]→[/]  Create an API key at: {conf['hint']}")
        chiave = Prompt.ask(f"  [bold]{conf['env_key']}[/]", default=esistente or '', show_default=False)
        if chiave.strip():
            scrivi_env(workspace, conf['env_key'], chiave.strip())
    console.print()
    console.print(f"  [dim]Model: press Enter for the default ({conf['modello']}). Models change frequently; enter a different model here when needed.[/]")
    modello = Prompt.ask('  [bold]Model[/]', default=(env.get('VIDEO_AI_MODEL') or '').strip() or conf['modello'])
    scrivi_env(workspace, 'VIDEO_AI_MODEL', modello.strip() or conf['modello'])
    console.print()
    if sorgente == 'hybrid':
        console.print('  [dim]Maximum generated clips per video. This caps spending; Pexels supplies the remaining clips.[/]')
        default_max = (env.get('VIDEO_AI_MAX_CLIPS') or '6').strip()
    else:
        console.print('  [bold yellow]⚠[/]  In AI-only mode, an 8-minute video requires approximately 96 generated clips.')
        console.print('  [dim]Below this limit, editing reuses generated clips instead of downloading more.[/]')
        default_max = (env.get('VIDEO_AI_MAX_CLIPS') or '12').strip()
    massimo = Prompt.ask('  [bold]Maximum AI clips per video[/]', default=default_max)
    try:
        massimo = str(max(1, int(''.join((c for c in massimo if c.isdigit())) or default_max)))
    except ValueError:
        massimo = default_max
    scrivi_env(workspace, 'VIDEO_AI_MAX_CLIPS', massimo)
    console.print()
    console.print(f'  [bold green]✓[/]  {stato(workspace)}')
    _prova_generazione(console)
    return sorgente

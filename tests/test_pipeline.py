import array,ast,importlib,json,os,sys,tempfile,unittest,wave,hashlib,subprocess
from pathlib import Path
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PIL import Image
from moduli import shorts,local_voice,audio

def asset_pack(root):
    folder=root/'assets/animation';folder.mkdir(parents=True,exist_ok=True)
    for name,size in [('poses.png',(96,64)),('walk-cycle.png',(128,64)),('puff-cycle.png',(96,32))]:Image.new('RGBA',size,(70,100,130,255)).save(folder/name)
    (folder/'walk-cycle.json').write_text(json.dumps([{'mouth':[16,12],'floor':30}]*8))
    manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
    (folder/'approved-animation-sha256.json').write_text(json.dumps(manifest))
    return folder

def wav_file(path,seconds):
    with wave.open(str(path),'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(24000)
        block=array.array('h',[1000,-1000]*12000).tobytes()
        for _ in range(seconds):w.writeframes(block)

class PipelineTests(unittest.TestCase):
 def setUp(self):
    self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.cwd=Path.cwd();os.chdir(self.root)
    self.env=patch.dict(os.environ,{'TUBE_WORKSPACE':str(self.root),'X264_PRESET':'ultrafast','FFMPEG_THREADS':'2'});self.env.start();asset_pack(self.root)
    for name in ['moduli.mascot','moduli.mascot_walk']:sys.modules.pop(name,None)
 def tearDown(self):self.env.stop();os.chdir(self.cwd);self.tmp.cleanup()
 def test_import_closure_and_removed_dependencies(self):
    expected_removed={'web_search','telegram_handler','asset','video_ai','thumbnail','montaggio','cervello','analytics','canale','strategia','scheduling','state_io','notifiche','memoria','manutenzione','preflight','logsetup','impostazioni_video','sottotitoli'}
    for name in expected_removed:self.assertFalse((ROOT/'moduli'/f'{name}.py').exists())
    for p in (ROOT/'moduli').glob('*.py'):importlib.import_module('moduli.'+p.stem)
    for p in ROOT.rglob('*.py'):
        if 'tests' in p.parts:continue
        for n in ast.walk(ast.parse(p.read_text())):
            if isinstance(n,ast.ImportFrom) and n.module and n.module.startswith('moduli.'):
                self.assertTrue((ROOT/Path(*n.module.split('.'))).with_suffix('.py').is_file(),str(p)+': '+n.module)
    req=(ROOT/'requirements.txt').read_text().lower()
    for name in ['moviepy','telegram','edge-tts','gtts','ddgs','anthropic']:self.assertNotIn(name,req)
 def test_runner_uses_kept_renderer_and_resumes_completed_job(self):
    import paul_revere as runner
    runner.ROOT=self.root
    editorial=self.root/'editorial.json';closing=' '.join(['closing']*35)
    editorial.write_text(json.dumps({'title':'Trump animation test','script':' '.join(['example']*190)+' '+closing,'closing_script':closing}))
    mascot=importlib.import_module('moduli.mascot')
    def narration(content,path):Path(path).write_bytes(b'narration')
    def render(audio,output,**kwargs):Path(output).write_bytes(b'video')
    with patch.object(mascot,'generate_host_audio',side_effect=narration),patch.object(shorts,'render_short',side_effect=render) as render_call,patch.object(shorts,'validate_short',return_value={'valid':True}):
        runner.produce('check',{},editorial=str(editorial))
        state=json.loads((self.root/'runs/check/checkpoint.json').read_text());self.assertTrue(state['complete']);self.assertTrue(state['render_done'])
        runner.produce('check',{},editorial=str(editorial));self.assertEqual(render_call.call_count,1)
 def test_publisher_records_upload_before_thumbnail_failure(self):
    from moduli import pubblica
    yt=Mock();request=yt.videos.return_value.insert.return_value;request.next_chunk.return_value=(None,{'id':'video-123'})
    yt.thumbnails.return_value.set.return_value.execute.side_effect=RuntimeError('thumbnail unavailable')
    recorded=[]
    with patch.object(pubblica,'_get_youtube',return_value=yt),patch.object(pubblica,'MediaFileUpload'):
        result=pubblica.pubblica_video('video.mp4','cover.jpg',{'title':'Test'},immediate=True,on_uploaded=recorded.append)
    self.assertEqual(result,'video-123');self.assertEqual(recorded,['video-123'])
    status=yt.videos.return_value.insert.call_args.kwargs['body']['status'];self.assertEqual(status['privacyStatus'],'private');self.assertNotIn('publishAt',status)
 def test_schedule_must_come_from_runner(self):
    from moduli import pubblica
    with patch.object(pubblica,'_get_youtube'),self.assertRaisesRegex(ValueError,'explicit publish_at'):
        pubblica.pubblica_video('video.mp4','cover.jpg',{'title':'Test'})
 def test_local_voice_adapter_and_cached_native_flow(self):
    with patch('moduli.local_voice.synthesize') as synth:audio.genera_audio('Selected words','out.mp3');synth.assert_called_once_with('Selected words','out.mp3')
    local_voice.ROOT=self.root
    (self.root/'voice-profile.json').write_text(json.dumps({'provider':'qwen-local','instruction':'Test voice instruction','reference_text':'Test reference transcript'}))
    calls=[]
    def native(command,text):
        calls.append((command,text));p=Path(command[command.index('-o')+1]);p.parent.mkdir(parents=True,exist_ok=True);wav_file(p,1)
    with patch.object(local_voice,'run',native):
        local_voice.synthesize('Example words.',self.root/'one.mp3');local_voice.synthesize('Example words.',self.root/'two.mp3')
    self.assertEqual(len(calls),2);self.assertTrue((self.root/'two.mp3').stat().st_size>1024)
 def test_selected_artwork_verification(self):
    from paul_revere_animation_guard import verify_approved_animation
    verify_approved_animation();(self.root/'assets/animation/poses.png').write_bytes(b'tampered')
    with self.assertRaisesRegex(RuntimeError,'failed verification'):verify_approved_animation()
 def test_real_short_composition_without_stock_or_video_providers(self):
    from moduli.ffmpeg_utils import ffmpeg_path
    mascot=importlib.import_module('moduli.mascot');source=self.root/'narration.wav';wav_file(source,90)
    def local_layer(audio,output,**kwargs):
        subprocess.run([ffmpeg_path(),'-y','-v','error','-f','lavfi','-i','color=c=white:s=1080x1920:r=30','-t','90','-an','-c:v','libx264','-preset','ultrafast','-threads','2','-pix_fmt','yuv420p',str(output)],check=True)
    with patch.object(mascot,'render_mascot',side_effect=local_layer):
        shorts.render_short(source,self.root/'short.mp4',captions_text=' '.join(['example']*225))
    info=shorts.validate_short(self.root/'short.mp4');self.assertTrue(info)
    self.assertTrue((self.root/'short.mp4').is_file())
    music=self.root/'chosen music.wav';wav_file(music,1)
    with patch.object(mascot,'render_mascot',side_effect=AssertionError('Expected cached mascot layer')):
        shorts.render_short(source,self.root/'music-short.mp4',custom_music=music)
    self.assertTrue(shorts.validate_short(self.root/'music-short.mp4'))

if __name__=='__main__':unittest.main()

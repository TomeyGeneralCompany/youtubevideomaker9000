import array,ast,importlib,json,os,sys,tempfile,unittest,wave,hashlib,subprocess
from pathlib import Path
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PIL import Image
from mavis import shorts,local_voice,audio

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
    reviewer=patch("mavis.editorial_policy.review");self.review=reviewer.start();self.addCleanup(reviewer.stop)
    self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.cwd=Path.cwd();os.chdir(self.root)
    self.env=patch.dict(os.environ,{'TUBE_WORKSPACE':str(self.root),'X264_PRESET':'ultrafast','FFMPEG_THREADS':'2'});self.env.start();asset_pack(self.root)
    for name in ['mavis.mascot','mavis.mascot_walk']:sys.modules.pop(name,None)
 def tearDown(self):self.env.stop();os.chdir(self.cwd);self.tmp.cleanup()
 def test_runtime_imports_resolve(self):
    for p in (ROOT/'mavis').glob('*.py'):importlib.import_module('mavis.'+p.stem)
    for p in ROOT.rglob('*.py'):
        if 'tests' in p.parts:continue
        for n in ast.walk(ast.parse(p.read_text())):
            if isinstance(n,ast.ImportFrom) and n.module and n.module.startswith('mavis.'):
                self.assertTrue((ROOT/Path(*n.module.split('.'))).with_suffix('.py').is_file(),str(p)+': '+n.module)
 def test_runner_uses_kept_renderer_and_resumes_completed_job(self):
    import run_mavis as runner
    runner.ROOT=self.root
    editorial=self.root/'editorial.json';closing=' '.join(['closing']*35)
    editorial.write_text(json.dumps({'title':'Garden animation test','script':' '.join(['example']*190)+' '+closing,'closing_script':closing}))
    mascot=importlib.import_module('mavis.mascot')
    def narration(content,path):Path(path).write_bytes(b'narration')
    def render(audio,output,**kwargs):
        Path(output).write_bytes(b'video');return {'valid':True}
    with patch.object(mascot,'generate_host_audio',side_effect=narration),patch.object(shorts,'render_short',side_effect=render) as render_call,patch.object(shorts,'validate_short',return_value={'valid':True}):
        runner.produce('check',{},editorial=str(editorial))
        state=json.loads((self.root/'runs/check/checkpoint.json').read_text());self.assertTrue(state['complete']);self.assertTrue(state['render_done'])
        runner.produce('check',{},editorial=str(editorial));self.assertEqual(render_call.call_count,1)
 def test_editorial_rejection_stops_before_narration_or_render(self):
    import run_mavis as runner
    runner.ROOT=self.root
    self.review.side_effect=ValueError('Editorial policy rejected this job')
    folder=self.root/'runs/blocked';folder.mkdir(parents=True)
    (folder/'checkpoint.json').write_text(json.dumps({'content':{'title':'Test','script':'Test'}}))
    with patch.object(shorts,'render_short') as render:
        with self.assertRaisesRegex(ValueError,'Editorial policy'):
            runner.produce('blocked',{})
        render.assert_not_called()
    self.assertFalse((folder/'narration.wav').exists())
    self.assertEqual(json.loads((folder/'checkpoint.json').read_text())['stage'],'Editorial review')
 def test_publisher_records_upload_before_thumbnail_failure(self):
    import run_mavis as runner
    from mavis import youtube_upload
    runner.ROOT=self.root
    folder=self.root/'runs/upload';folder.mkdir(parents=True)
    for name in ['narration.wav','short.mp4','thumbnail.jpg']:(folder/name).touch()
    state=folder/'checkpoint.json'
    state.write_text(json.dumps({'content':{'title':'Test','script':'Test'},'audio_done':True,
                                 'audio_version':'mascot-ready-v4','render_done':True,
                                 'renderer_version':'mascot-approved-cels-20261015-r1',
                                 'cover_version':'mascot-approved-cels-20261015-r1'}))
    yt=Mock();request=yt.videos.return_value.insert.return_value
    request.next_chunk.return_value=(None,{'id':'video-123'})
    def thumbnail_failure():
        self.assertEqual(json.loads(state.read_text())['video_id'],'video-123')
        raise RuntimeError('thumbnail unavailable')
    thumb=yt.thumbnails.return_value.set.return_value.execute
    thumb.side_effect=thumbnail_failure
    with patch.object(runner,'youtube_session',return_value=(yt,'channel-123')) as session, \
         patch.object(youtube_upload,'MediaFileUpload'),patch.object(shorts,'validate_short',return_value={}):
        runner.produce('upload',{},upload=True)
        runner.produce('upload',{},upload=True)
    session.assert_called_once()
    request.next_chunk.assert_called_once_with(num_retries=5)
    thumb.assert_called_once()
    status=yt.videos.return_value.insert.call_args.kwargs['body']['status']
    self.assertEqual(status['privacyStatus'],'private');self.assertNotIn('publishAt',status)
 def test_schedule_must_come_from_runner(self):
    from datetime import datetime, timedelta, timezone
    from mavis import youtube_upload
    yt=Mock()
    with self.assertRaisesRegex(ValueError,'explicit publish_at'):
        youtube_upload.prepare_video_transfer(yt,'video.mp4',{'title':'Test'})
    yt.videos.assert_not_called()
    with patch.object(youtube_upload,'MediaFileUpload'):
        youtube_upload.prepare_video_transfer(yt,'video.mp4',{'title':'Test'},
            publish_at=datetime(2030,1,1,18,tzinfo=timezone(timedelta(hours=-5))))
    self.assertEqual(yt.videos.return_value.insert.call_args.kwargs['body']['status']['publishAt'],
                     '2030-01-01T23:00:00Z')
 def test_local_voice_adapter_and_cached_native_flow(self):
    with patch('mavis.local_voice.synthesize') as synth:audio.generate_audio('Selected words','out.mp3');synth.assert_called_once_with('Selected words','out.mp3')
    local_voice.ROOT=self.root
    (self.root/'voice-profile.json').write_text(json.dumps({'provider':'qwen-local','instruction':'Test voice instruction','reference_text':'Test reference transcript'}))
    calls=[]
    def native(command,text):
        calls.append((command,text));p=Path(command[command.index('-o')+1]);p.parent.mkdir(parents=True,exist_ok=True);wav_file(p,1)
    with patch.object(local_voice,'run',native),patch.object(local_voice,'design',wraps=local_voice.design) as reference:
        local_voice.synthesize('Example words.',self.root/'one.mp3');local_voice.synthesize('Example words.',self.root/'two.mp3')
    reference.assert_called_once()
    self.assertEqual(len(calls),2);self.assertTrue((self.root/'two.mp3').stat().st_size>1024)
 def test_selected_artwork_verification(self):
    from mavis.animation_guard import verify_approved_animation
    verify_approved_animation();(self.root/'assets/animation/poses.png').write_bytes(b'tampered')
    with self.assertRaisesRegex(RuntimeError,'failed verification'):verify_approved_animation()
 def test_real_short_composition_without_stock_or_video_providers(self):
    from mavis.ffmpeg_utils import ffmpeg_path
    mascot=importlib.import_module('mavis.mascot');source=self.root/'narration.wav'
    with wave.open(str(source),'wb') as wav:
        wav.setparams((2,2,48000,0,'NONE','not compressed'))
        for _ in range(90):
            wav.writeframes(b'\xe8\x03\x18\xfc' * 48000)
    def local_layer(audio,output,**kwargs):
        subprocess.run([ffmpeg_path(),'-y','-v','error','-f','lavfi','-i','color=c=white:s=1080x1920:r=30','-t','90','-an','-c:v','libx264','-preset','ultrafast','-threads','2','-pix_fmt','yuv420p',str(output)],check=True)
    with patch.object(mascot,'render_mascot',side_effect=local_layer),patch.object(shorts,'fit_narration',side_effect=AssertionError('Narration is already fitted')):
        info=shorts.render_short(source,self.root/'short.mp4',captions_text=' '.join(['example']*225))
        self.assertEqual(info['streams'][0]['width'],1080)
    info=shorts.validate_short(self.root/'short.mp4');self.assertTrue(info)
    self.assertTrue((self.root/'short.mp4').is_file())
    music=self.root/'chosen music.wav';wav_file(music,1)
    with patch.object(mascot,'render_mascot',side_effect=AssertionError('Expected cached mascot layer')):
        shorts.render_short(source,self.root/'music-short.mp4',custom_music=music)
    self.assertTrue(shorts.validate_short(self.root/'music-short.mp4'))
    old=shorts._layer_signature(source,'title')
    (self.root/'media-profile.json').write_text(json.dumps({'animation':{'ground_y':1300}}))
    self.assertNotEqual(shorts._layer_signature(source,'title'),old)

 def test_script_writer_stops_after_three_invalid_responses(self):
    from mavis import ai_client, media_research
    with patch.object(ai_client,'chat_ollama',return_value='incomplete') as write:
        with self.assertRaisesRegex(RuntimeError,'No validated mascot script'):
            media_research.write_mascot_content('Test topic',{'sources':[]})
    self.assertEqual(write.call_count,3)
    self.assertIn('Previous attempt failed validation',write.call_args.args[0])

if __name__=='__main__':unittest.main()

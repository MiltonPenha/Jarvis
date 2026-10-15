"""Prepare the pinned CPU voice without changing AI, microphone or active settings."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.safety import atomic_write


def sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024), b''):digest.update(chunk)
    return digest.hexdigest()


def main():
    import httpx
    lab=ROOT/'.runtime/voice-lab'
    lab.mkdir(parents=True,exist_ok=True)
    spec=json.loads((ROOT/'scripts/qwen_voice_assets.json').read_text(encoding='utf-8'))
    if not (lab/'packages/transformers/__init__.py').is_file():
        uv=ROOT/'.runtime/tools/uv-0.12.3-win32-x64/uv.exe'
        subprocess.run([str(uv),'pip','install','--target',str(lab/'packages'),'-r',
                        str(ROOT/'requirements.voice-cpu.lock.txt')],check=True)
    needed=[(name,item) for name,item in spec['files'].items()
            if not (lab/name).is_file() or sha(lab/name)!=item['sha256']]
    if shutil.disk_usage(lab).free < sum(item['size'] for _,item in needed)+3*2**30:
        raise SystemExit('Libere espaço: o preparo mantém uma reserva de 3 GiB no disco.')
    with httpx.Client(timeout=90,follow_redirects=True) as client:
        for name,item in needed:
            target=lab/name;target.parent.mkdir(parents=True,exist_ok=True)
            temporary=target.with_suffix(target.suffix+'.part')
            print('Preparando '+name,flush=True)
            try:
                with client.stream('GET',item['url']) as response:
                    response.raise_for_status()
                    with temporary.open('wb') as output:
                        for chunk in response.iter_bytes(1024*1024):output.write(chunk)
                if temporary.stat().st_size!=item['size'] or sha(temporary)!=item['sha256']:
                    raise ValueError('Checksum do arquivo Qwen não confere: '+name)
                temporary.replace(target)
            finally:temporary.unlink(missing_ok=True)
        atomic_write(lab/'model/manifest.json',json.dumps(spec['manifest']))
        refs_ready=all((lab/name).is_file() and sha(lab/name)==digest for name,digest in spec['reference_files'].items())
        if not refs_ready:
            voice=client.get('https://api.fish.audio/model/'+spec['voice_id']).raise_for_status().json()
            sample=next((s for s in voice.get('samples',[]) if s['task_id']==spec['reference_task']),None)
            if not sample:raise ValueError('A referência pública mudou; não será usada outra voz automaticamente.')
            audio=client.get(sample['audio']).raise_for_status().content
            if hashlib.sha256(audio).hexdigest()!=spec['reference_mp3_sha256']:
                raise ValueError('A amostra pública não corresponde à voz preparada.')
            (lab/'reference.mp3').write_bytes(audio)
            ffmpeg=ROOT/'.runtime/tools/ffmpeg-9.0.1-win32-x64/bin/ffmpeg.exe'
            subprocess.run([str(ffmpeg),'-hide_banner','-loglevel','error','-y','-i',str(lab/'reference.mp3'),
                '-ac','1','-ar','24000',str(lab/'reference-full.wav')],check=True,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            import soundfile as sf
            data,rate=sf.read(lab/'reference-full.wav',dtype='float32')
            sf.write(lab/'reference.wav',data[:int(spec['reference_seconds']*rate)],rate)
            atomic_write(lab/'reference-short-text.txt',sample['text'].split('?')[0]+'?')
            if not all(sha(lab/name)==digest for name,digest in spec['reference_files'].items()):
                raise ValueError('A referência local não confere com a amostra verificada.')
    print('Qwen CPU preparado. Selecione Qwen local em Síntese. Gemini, microfone e preferências foram preservados.')


if __name__=='__main__':main()

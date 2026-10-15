"""Fish Audio synthesis using the user's exact public voice. No fallback/retries."""
import asyncio
from pathlib import Path

import httpx

from core.config import config, provider_key

VOICE_ID = 'a5b93aeddcc948c19ea04f0afe9d178c'
VOICE_TITLE = 'Jarvis (UCM) - Português Brasileiro'
ENGINES = ('s1', 's2-pro', 's2.1-pro', 's2.1-pro-free', 'drama-3')


class FishVoiceError(ValueError):
    """Only locally written, safe-to-display messages belong in this exception."""


class FishVoiceCancelled(Exception):
    pass


def voice_status():
    return {'voice_id': VOICE_ID, 'title': VOICE_TITLE, 'engine': config.FISH_TTS_MODEL,
            'configured': bool(provider_key('fish-audio'))}


async def synthesize(text, path, cancel=None, *, transport=None):
    key = provider_key('fish-audio').strip()
    if not key:
        raise FishVoiceError('Configure FISH_API_KEY no .env e reinicie o JARVIS para usar esta voz.')
    if config.FISH_TTS_MODEL not in ENGINES:
        # Fish silently uses its paid default for unknown headers. Reject them locally.
        raise FishVoiceError('FISH_TTS_MODEL inválido. Use s2.1-pro-free ou um motor oficial da Fish Audio.')
    if cancel is not None and cancel.is_set():
        raise FishVoiceCancelled()

    async def download():
        async with httpx.AsyncClient(timeout=httpx.Timeout(25, connect=10), transport=transport) as client:
            async with client.stream('POST', 'https://api.fish.audio/v1/tts',
                    headers={'Authorization': f'Bearer {key}', 'model': config.FISH_TTS_MODEL},
                    json={'text': text, 'reference_id': VOICE_ID, 'format': 'mp3',
                          'sample_rate': 44100, 'mp3_bitrate': 128, 'latency': 'balanced',
                          'prosody': {'speed': 1, 'volume': 0, 'normalize_loudness': True}}) as response:
                if response.status_code != 200:
                    messages = {
                        401: 'Chave Fish Audio recusada. Confira FISH_API_KEY no .env e reinicie o JARVIS.',
                        403: 'A conta Fish Audio não tem acesso a esta voz ou motor.',
                        402: 'A Fish Audio exige saldo ou acesso ao motor escolhido. Confira sua conta.',
                        404: 'A voz solicitada não está disponível na Fish Audio.',
                        429: 'Limite da Fish Audio atingido. Aguarde antes de tentar novamente.',
                    }
                    raise FishVoiceError(messages.get(response.status_code,
                        f'Fish Audio indisponível (HTTP {response.status_code}). Tente novamente mais tarde.'))
                content_type = response.headers.get('content-type', '').split(';')[0].strip().lower()
                if content_type not in ('audio/mpeg', 'audio/mp3', 'application/octet-stream'):
                    raise FishVoiceError('A Fish Audio não retornou áudio MP3 válido.')
                size = 0
                with Path(path).open('wb') as output:
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > 8_000_000:
                            raise FishVoiceError('Áudio Fish Audio maior que o limite de reprodução.')
                        output.write(chunk)
                if not size:
                    raise FishVoiceError('A Fish Audio retornou áudio vazio.')

    task = asyncio.create_task(download())
    completed = False
    try:
        async with asyncio.timeout(40):
            while not task.done():
                await asyncio.wait({task}, timeout=.05)
                if cancel is not None and cancel.is_set():
                    raise FishVoiceCancelled()
            await task
            completed = True
    except (httpx.TimeoutException, TimeoutError):
        raise FishVoiceError('A Fish Audio demorou para gerar a voz. Tente novamente mais tarde.') from None
    except httpx.HTTPError:
        raise FishVoiceError('Não foi possível conectar à Fish Audio. Confira a conexão com a internet.') from None
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if not completed:
            Path(path).unlink(missing_ok=True)

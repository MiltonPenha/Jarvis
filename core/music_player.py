"""Launch a music destination without claiming playback we cannot observe."""
from urllib.parse import quote_plus
from core.automation import automation_service

class MusicPlayer:
    def play_music(self,song_name):
        url='https://www.youtube.com/results?search_query='+quote_plus(song_name)
        automation_service.open_url(url)
        return True,'Busca de música aberta no YouTube. Selecione a faixa para reproduzir.'

music_player=MusicPlayer()

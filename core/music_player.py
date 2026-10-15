import os
import sys
import ctypes
import subprocess
import threading
from typing import Optional

from core.automation import automation_service

class MusicPlayer:
    def __init__(self):
        self.user32 = ctypes.windll.user32
        self.VK_MEDIA_PLAY_PAUSE = 0xB3
        self.VK_MEDIA_STOP = 0xB2
        self.VK_MEDIA_NEXT_TRACK = 0xB0
        self.VK_MEDIA_PREV_TRACK = 0xB1
        self.last_played = None

    def play_music(self, song_name: str) -> tuple[bool, str]:
        """
        Searches and plays a requested song immediately.
        Finds the exact match on YouTube or opens Spotify.
        """
        clean_name = song_name.strip()
        if not clean_name:
            # If no song specified, resume media
            self.toggle_play_pause()
            return True, "Retomando reprodução de áudio, senhor."

        self.last_played = clean_name

        def _search_and_launch():
            try:
                # Use yt-dlp to quickly find the exact top YouTube video ID
                cmd = ["python", "-m", "yt_dlp", f"ytsearch1:{clean_name}", "--get-id", "--no-warnings"]
                video_id = subprocess.check_output(cmd, text=True, timeout=12).strip()
                if video_id:
                    url = f"https://www.youtube.com/watch?v={video_id}"
                    automation_service.open_url(url)
                    return
            except Exception:
                pass

            # Fallback to direct YouTube search page
            fallback_url = f"https://www.youtube.com/results?search_query={clean_name.replace(' ', '+')}"
            automation_service.open_url(fallback_url)

        # Launch in background thread so it doesn't block assistant speech
        threading.Thread(target=_search_and_launch, daemon=True).start()
        return True, f"Iniciando reprodução de '{clean_name}', senhor."

    def play_spotify(self, song_name: str = "") -> tuple[bool, str]:
        """Searches or opens Spotify."""
        if song_name:
            url = f"https://open.spotify.com/search/{song_name.replace(' ', '%20')}"
            automation_service.open_url(url)
            return True, f"Buscando '{song_name}' no Spotify."
        else:
            automation_service.open_target("spotify")
            return True, "Abrindo Spotify."

    def toggle_play_pause(self):
        """Toggles play/pause on Windows media."""
        self.user32.keybd_event(self.VK_MEDIA_PLAY_PAUSE, 0, 0, 0)
        self.user32.keybd_event(self.VK_MEDIA_PLAY_PAUSE, 0, 2, 0)

    def next_track(self):
        """Skips to next track."""
        self.user32.keybd_event(self.VK_MEDIA_NEXT_TRACK, 0, 0, 0)
        self.user32.keybd_event(self.VK_MEDIA_NEXT_TRACK, 0, 2, 0)

    def previous_track(self):
        """Goes to previous track."""
        self.user32.keybd_event(self.VK_MEDIA_PREV_TRACK, 0, 0, 0)
        self.user32.keybd_event(self.VK_MEDIA_PREV_TRACK, 0, 2, 0)

    def stop(self):
        """Stops media playback."""
        self.user32.keybd_event(self.VK_MEDIA_STOP, 0, 0, 0)
        self.user32.keybd_event(self.VK_MEDIA_STOP, 0, 2, 0)

music_player = MusicPlayer()

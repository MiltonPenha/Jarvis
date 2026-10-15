"""Explicit opt-in; starting JARVIS never enables autostart by itself."""
from core.autostart import autostart_service
if __name__=='__main__':
    ok,message=autostart_service.enable()
    print(message)
    raise SystemExit(0 if ok else 1)

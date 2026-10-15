import sys
from core.autostart import autostart_service

def main():
    if len(sys.argv) > 1 and sys.argv[1].lower() in ["disable", "desativar", "off"]:
        success, msg = autostart_service.disable()
        print(f"[-] {msg}")
    elif len(sys.argv) > 1 and sys.argv[1].lower() in ["status"]:
        status = autostart_service.is_enabled()
        print(f"[*] Inicialização no boot: {'ATIVADA' if status else 'DESATIVADA'}")
    else:
        success, msg = autostart_service.enable()
        print(f"[+] {msg}")

if __name__ == "__main__":
    main()

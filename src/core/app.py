from audio.recorder import list_audio_devices, record_audio
from utils.logger import log


def run() -> None:
    log("Jarvis inicializado.")
    print()
    print("1 - Listar dispositivos de áudio")
    print("2 - Gravar teste de áudio")
    print("0 - Sair")
    print()

    while True:
        choice = input("Escolha uma opção: ").strip()

        if choice == "1":
            list_audio_devices()
            print()
        elif choice == "2":
            path = record_audio()
            print(f"Arquivo gerado: {path}")
            print()
        elif choice == "0":
            log("Encerrando Jarvis.")
            break
        else:
            print("Opção inválida.\n")
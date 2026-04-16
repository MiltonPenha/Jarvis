from audio.recorder import list_audio_devices, record_audio
from audio.stt import transcribe_audio
from utils.logger import log


def run() -> None:
    log("Jarvis inicializado.")
    print()
    print("1 - Listar dispositivos de áudio")
    print("2 - Gravar e transcrever áudio")
    print("0 - Sair")
    print()

    while True:
        choice = input("Escolha uma opção: ").strip()

        if choice == "1":
            list_audio_devices()
            print()

        elif choice == "2":
            audio_path = record_audio()
            texto = transcribe_audio(audio_path)

            print(f"\n🧾 Resultado: {texto}\n")

        elif choice == "0":
            log("Encerrando Jarvis.")
            break

        else:
            print("Opção inválida.\n")
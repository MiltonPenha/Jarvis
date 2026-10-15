# ◈ J.A.R.V.I.S. - Assistente Pessoal de Inteligência Artificial v3.0
> *Inspirado no lendário sistema Stark Industries do Homem de Ferro, com Agente Hermes, Memória em Obsidian, Voz Britânica e HUD Holográfico.*

---

## ⚡ Novidades da Refatoração v3.0

1. **Agente Cognitivo Hermes**:
   - Raciocínio estruturado via tags `<thought>...</thought>` exibidas no terminal holográfico do HUD.
   - Chamada autônoma de ferramentas (*Tool Calling*) para automação do Windows, música e pesquisas.
   - Suporte unificado: modelo local via Ollama (`hermes3:8b`), OpenAI/Gemini ou fallback ilimitado de alto desempenho.

2. **Memória Neural Integrada com Obsidian**:
   - Cofre dedicado criado em: `C:\Users\PC Gamer\Documents\JARVIS-Memory`
   - Registro automático de diálogos diários em `Daily/YYYY-MM-DD.md`.
   - Perfil e preferências de usuário carregados em tempo real de `User/Perfil.md` e `User/Preferencias.md`.
   - Pesquisa de conhecimento salva com backlinks automáticos `[[Topico.md]]` na pasta `Knowledge/`.
   - Lista dinâmica de tarefas e lembretes em `Tasks/Tarefas.md`.

3. **Voz Britânica Clássica (Paul Bettany Style)**:
   - Síntese com a voz neural britânica `en-GB-RyanNeural` calibrada com pitch e cadência refinados, mantendo dicção clássica e elegante ao responder em português ou inglês.

4. **Gerenciamento Limpo de Ciclo de Vida**:
   - O Jarvis encerra todos os processos ao fechar a janela no "X" ou ao clicar no botão **"ENCERRAR"**.
   - Scripts rápidos: [`start_jarvis.bat`](file:///c:/Users/PC%20Gamer/Desktop/jarvis/start_jarvis.bat) e [`PARAR_JARVIS.bat`](file:///c:/Users/PC%20Gamer/Desktop/PARAR_JARVIS.bat) (na sua Área de Trabalho).

---

## 🎙️ Tabela de Comandos de Voz

| Categoria | Exemplo de Comando Falado | O que o Jarvis Faz |
|---|---|---|
| **Memória Obsidian** | *"Jarvis, anote que a reunião será às 15h"* | Salva uma nota de conhecimento no cofre Obsidian |
| **Tarefas Obsidian** | *"Jarvis, adicionar tarefa comprar café"* | Adiciona item com checkbox em `Tasks/Tarefas.md` |
| **Consulta Obsidian** | *"Jarvis, o que você lembra sobre reunião?"* | Pesquisa nas notas do cofre e lê o resumo |
| **Abrir Cofre** | *"Jarvis, abrir obsidian"* / *"Abrir cofre"* | Abre a pasta do cofre de memória no Explorador |
| **Saudações** | *"Jarvis, bom dia"* / *"Ei Jarvis, está aí?"* | Responde com saudação refinada no tom britânico |
| **Mídia** | *"Jarvis, tocar música AC/DC Back in Black"* | Abre o vídeo oficial no YouTube |
| **Controle de Mídia** | *"Jarvis, pausar música"* / *"Continuar música"* | Pausa ou retoma qualquer player no Windows |
| **Pesquisa Web** | *"Jarvis, pesquise sobre a missão Artemis"* | Realiza busca na web e registra no Obsidian |
| **Navegação & Apps** | *"Jarvis, abrir o YouTube"* / *"Abrir Discord"* | Executa o aplicativo ou site no navegador principal |
| **Volume** | *"Jarvis, aumentar volume"* / *"Mutar som"* | Controla o volume principal do sistema |
| **Captura de Tela** | *"Jarvis, tirar print"* | Captura a tela e salva em `Imagens/JARVIS` |
| **Janelas** | *"Jarvis, minimizar tudo"* | Minimiza todas as janelas abertas (Win+D) |
| **Segurança** | *"Jarvis, bloquear computador"* | Bloqueia a estação de trabalho |
| **Encerramento** | *"Jarvis, encerrar"* / *"Jarvis, fechar"* | Desliga todos os processos do sistema |

---

## 📂 Estrutura do Projeto

```
jarvis/
├── core/
│   ├── hermes_agent.py     # Agente cognitivo Hermes (Tool Calling & Thought Parsing)
│   ├── memory_obsidian.py  # Gerenciador do Cofre de Memória Obsidian
│   ├── config.py           # Configurações de voz britânica e parâmetros do sistema
│   ├── audio_manager.py    # Microfone, Reconhecimento de Voz (STT) e Fala (TTS)
│   ├── command_patterns.py # Motor de comandos de voz semânticos e atalhos
│   ├── llm_brain.py        # Orquestrador de Inteligência e ponte para o Hermes Agent
│   ├── automation.py       # Automação de apps, volume, arquivos e janelas
│   ├── music_player.py     # Localizador e reprodutor de músicas do YouTube/Spotify
│   ├── system_monitor.py   # Telemetria em tempo real (CPU, RAM, Disco, Uptime)
│   └── autostart.py        # Gerenciador de inicialização do Windows
├── web/
│   ├── index.html          # HUD Holográfico do Reator Arc
│   ├── style.css           # Estilos sci-fi com suporte a pensamentos Hermes
│   └── app.js              # Canvas 60 FPS, WebSockets e renderizador de pensamento
├── commands.json           # Macros customizadas pelo usuário
├── server.py               # Servidor FastAPI com WebSockets em tempo real
├── run_jarvis.py           # Orquestrador principal com desligamento inteligente
├── start_jarvis.bat        # Inicializador principal
├── stop_jarvis.bat         # Parada forçada de processos
└── .env                    # Configuração de voz e caminhos do cofre
```

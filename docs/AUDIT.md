# Auditoria e implementação — 15/10/2026

O pedido foi lido integralmente antes das alterações. Não havia `AGENTS.md`, manifesto de dependências, testes ou repositório Git na pasta. Foi feito backup dos arquivos originais em `%LOCALAPPDATA%/JarvisBackups/20261015-024821` e criado um snapshot Git inicial. Um literal semelhante a credencial encontrado no código legado foi removido também desse novo snapshot; os arquivos originais permanecem somente no backup externo local. Nenhum segredo foi incluído nos novos exemplos ou commits.

## Diagnóstico inicial

| Área | Evidência e problema | Tratamento |
|---|---|---|
| Stack | FastAPI/Uvicorn, HTML/CSS/Canvas/JS, sounddevice, SpeechRecognition, Edge TTS/pyttsx3 | Preservados; dependências reproduzíveis em ambiente próprio |
| Núcleo | `core/hermes_agent.py` dizia “Nous Hermes-inspired”; usava regex para tags e um único tool call | Substituído pela biblioteca oficial `run_agent.AIAgent`, via runtime isolado e registro oficial de ferramenta |
| Provedores | Ollama tinha precedência automática, modelos fixos, Gemini sem histórico completo, Pollinations sem configuração explícita | Seleção explícita OpenAI/Gemini pelo Hermes, catálogo atual consultável, fallback opt-in e visível |
| Memória | Markdown real no vault, com 1.154 caracteres de perfil/preferências e nenhuma nota de conhecimento no primeiro inventário | Vault preservado; perfil legado continua como fonte, memória essencial nova usa o store do Hermes |
| Persistência | Histórico do agente em lista Python; “salvei” vinha de mensagens não verificadas | SessionDB nativo; releitura após escrita, hashes, locks e revisões |
| Concorrência | REST, WS, listener de fundo e Web Speech podiam executar ao mesmo tempo; WS era usado com novos event loops em outras threads | Uma fila de execução; um dono do microfone; callbacks encaminhados ao loop do servidor |
| Voz | Voz britânica pronunciava português; engine COM criada no import; vários caminhos de escuta; fallback implícito; cancelamento incompleto | Voz pt-BR, inicialização tardia, provedores explícitos, cancelamento com geração, um pipeline de áudio |
| Ferramentas Windows | `shell=True` e fallback de execução arbitrária; música anunciava reprodução antes da thread resolver o destino | Lista de aplicativos, URLs validadas, sem shell livre; resultados distinguem solicitação ao Windows de estado observado |
| Interface | Identidade visual funcional; raciocínio interno exibido; refresh fechava backend; não havia controles operacionais consistentes | Reator preservado, painel operacional, tarefas/histórico/fontes/memória/consumo, sem fechamento por `beforeunload` |
| Ciclo de vida | `time` faltava em caminhos de shutdown; `os._exit`; parada por correspondência ampla; autostart em dois locais | Uvicorn com encerramento gracioso, árvore dos workers controlada e um registro de autostart |
| Segurança | CORS `*`, WS sem origem, sem limites de caminho, logs de argumentos de ferramentas | Host/Origin/cookie local, limites por ferramenta, segredos filtrados e acesso de arquivos resolvido |

## Reprodução antes da migração

`python -m uvicorn server:app --host 127.0.0.1 --port 8000` iniciou. Interface, `/api/status`, `/api/memory` e comando determinístico de status retornaram HTTP 200. A existência de um vault e de código de gravação não foi tratada como prova das capacidades posteriores: os testes novos usam vault e workspace temporários.

As credenciais herdadas tinham valores, mas a OpenAI recusou o catálogo com HTTP 401 e o Gemini com HTTP 403. Nenhum valor foi mostrado. A checagem foi repetida pelo diagnóstico final, com o mesmo resultado. Não se concluiu que os modelos seriam acessíveis apenas porque uma variável existia.

## Decisões e extensão

- O Hermes foi instalado pelo checkout oficial e PM. O bootstrap inicial falhou ao criar o link de uma versão menor de Python na instalação uv da máquina; `UV_PYTHON_INSTALL_DIR` isolado resolveu o erro. O procedimento está em `scripts/setup.ps1`, sem editar o Hermes.
- Integração de biblioteca foi escolhida por preservar o HUD e dar acesso oficial ao ciclo, sessões e callbacks. JSONL liga o servidor ao worker, permitindo interrompê-lo e evitar conflitos entre dependências.
- As ferramentas são registradas com `tools.registry.registry.register`, filtradas para o toolset `jarvis`. Não há segundo ciclo de chamadas ao modelo em código próprio. Operações determinísticas podem ser acionadas diretamente pela UI para evitar uma chamada desnecessária ao modelo.
- `SessionDB` e `MemoryStore` são nativos. O ledger separado existe para pedidos, deduplicação, estado e evidência de efeitos. O índice Obsidian é derivado, reconstruível e incremental; o Markdown é a fonte de conhecimento.
- Reflexão automática, resumo por modelo, embeddings e fallback auxiliar foram desativados. Não são necessários para as capacidades verificadas e adicionariam chamadas externas sem evidência de benefício.
- Efeitos com resultado incerto não são repetidos. O sistema não pode oferecer atomicidade distribuída entre SQLite e Windows/serviços externos; bloquear a retomada incerta é a decisão explícita.
- Skills exigem evidência de unittest aprovado com testes reais. Skills lidas são dados de menor prioridade e não podem aumentar a superfície de ferramentas ou permissões.

## Fontes consultadas

Implementação da integração, instalação e persistência foi conferida na documentação e no código da revisão oficial, sem patches internos:

- [Hermes como biblioteca Python](https://hermes-agent.nousresearch.com/docs/guides/python-library)
- [Instalação oficial, inclusive Windows](https://hermes-agent.nousresearch.com/docs/getting-started/installation)
- [Integração programática](https://hermes-agent.nousresearch.com/docs/developer-guide/programmatic-integration)
- [Provedores do Hermes](https://hermes-agent.nousresearch.com/docs/integrations/providers)
- [PM e ambientes](https://hermes-agent.nousresearch.com/docs/reference/package-management)
- [Revisão oficial usada](https://github.com/NousResearch/hermes-agent/tree/7bda2a3368024f7ae1c70cef16583e7c2c891674)
- [OpenAI — listar modelos](https://developers.openai.com/api/reference/resources/models/methods/list)
- [Gemini — catálogo e capacidades dos modelos](https://ai.google.dev/api/models)
- [OpenAI — síntese de fala](https://developers.openai.com/api/reference/resources/audio/subresources/speech/methods/create)
- [edge-tts — implementação e licença](https://github.com/rany2/edge-tts)
- [faster-whisper — opções locais CPU/int8 e licença](https://github.com/SYSTRAN/faster-whisper)

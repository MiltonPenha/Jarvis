# Revisão de limpeza — 15/10/2026

O projeto usa JARVIS/FastAPI, Hermes Agent oficial e provedores OpenAI/Gemini. O Ollama e o modelo local Hermes 3 não fazem parte da execução atual. Dados do usuário, vault, histórico, tarefas, preferências de voz e dependências do runtime foram mantidos.

## Configuração local

O `.env` foi refeito a partir do exemplo atual, preservando as credenciais utilizadas, os caminhos e os valores aplicáveis. `TTS_VOICE`, `TTS_RATE` e `TTS_PITCH` foram migrados para `JARVIS_TTS_VOICE`, `JARVIS_TTS_RATE` e `JARVIS_TTS_PITCH`. Foram retirados `HERMES_MODEL`, `OLLAMA_URL`, `OLLAMA_MODEL`, `GROQ_API_KEY`, `USER_NAME`, `JARVIS_NAME` e os comentários sobre fallback gratuito ilimitado. Esses campos não eram consumidos pela implementação atual.

O provedor salvo foi ajustado para Gemini porque o usuário configurou essa chave e a escolha anterior era o default OpenAI, sem modelo. Nenhum modelo foi escolhido automaticamente; o usuário deve selecioná-lo na lista e salvar.

## Código e interface

- Campos sem consumidores removidos de Config: nomes do usuário/assistente, arquivo de ambiente redundante, lista antiga de palavras de ativação, volume offline fixo e limiares antigos do SpeechRecognition. A palavra de ativação continua tratada pela escuta contínua atual; o VAD usa `JARVIS_VAD_THRESHOLD`.
- Métodos sem chamadas removidos: leitura/busca de perfil antigo em ObsidianMemory, resumo de voz duplicado em SystemMonitor e atalho Spotify separado sem uso. O vault continua pesquisável; Spotify continua disponível nas macros e nos aplicativos conhecidos.
- Rota antiga `/api/memory/open` removida; o atalho Cofre Obsidian usa `/api/actions`, com a mesma política de ferramentas e checkpoints das outras ações.
- Flags/argumento/logger sem consumidores removidos de AudioManager, junto com imports sem uso. A exclusão mútua do microfone e o cancelamento continuam ativos.
- Elemento de áudio vazio, estilos antigos de pensamentos, variáveis CSS sem referências e estado STANDBY não emitido foram removidos. Os cabeçalhos do terminal usam agora os estilos existentes de remetente e horário.
- `speech_response` foi removido das macros porque o executor não usava esse campo; gatilhos e destinos foram mantidos.
- O datalist foi substituído por seletores de modelos. Catálogos principal/fallback são independentes, carregam ao abrir o painel e ao mudar de provedor e descartam respostas atrasadas de consultas anteriores. Erros aparecem junto ao campo; a escolha salva sobrevive a falhas de consulta. O catálogo Gemini exclui famílias especializadas em imagem, música, transcrição, TTS e controle de computador.

## Arquivos locais e dependências

As cópias avulsas de documentação em `.runtime/docs`, o script de saneamento inicial `.runtime/sanitize_baseline.py` e o log antigo da raiz `jarvis_out.log` foram arquivados fora do projeto. Caches Python das pastas próprias foram limpos; serão recriados sob demanda. O checkout oficial do Hermes não foi editado. Os ambientes Python, ferramentas do runtime, scripts de diagnóstico/validação, iniciadores e macros têm usos válidos e foram mantidos.

Todos os 67 pacotes instalados na `.venv` pertencem ao grafo das dependências atuais ou às ferramentas de instalação. Nenhum pacote foi removido por confundir dependência transitiva com sobra.

Backup local anterior à limpeza: `%LOCALAPPDATA%/JarvisBackups/cleanup-20261015-140602`. Contém o `.env` anterior, as preferências e os arquivos arquivados. Contém informações privadas; não deve ser versionado ou compartilhado.

## Verificação

36 testes Python e 4 testes JavaScript passaram. Os testes incluem consulta de catálogo, erro de credencial, catálogos de fallback separados, manutenção do modelo salvo e descarte de respostas atrasadas após trocar de provedor. `pip check` passou.

O servidor foi reiniciado com `--no-browser`. O navegador interno confirmou 19 modelos Gemini carregados automaticamente e o G522 selecionado. Nenhuma janela extra do Chrome foi aberta e nenhuma geração paga foi realizada. Evidência visual local: `.data/validation/modelos-corrigidos.png`. A seleção do modelo e a primeira conversa real permanecem pendentes do usuário.

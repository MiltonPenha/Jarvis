# Voz e transcrição locais — 15/10/2026

A configuração solicitada mantém **Gemini pela API para o raciocínio** e usa **Whisper local para reconhecer a fala** e **SAPI/Windows para a voz**. O microfone G522 permanece selecionado. Não há integração com Ollama, modelo local de raciocínio ou fallback automático para serviços de voz online.

O áudio do microfone é processado pelo Whisper no computador. O texto reconhecido é enviado ao Gemini como pedido; o texto da resposta volta e é sintetizado pela voz brasileira instalada no Windows (Maria nesta máquina). A latência da API Gemini continua existindo.

## Preparação e execução

`scripts/setup_voice.ps1` instala as dependências travadas, baixa o Whisper `base` multilíngue se necessário e salva somente `tts_provider=offline` e `stt_provider=whisper-local`. Preserva modelo/provedor de IA, credenciais, microfone e outras preferências. O download é feito na preparação; durante a transcrição `local_files_only=True` impede novos downloads.

O Whisper usa CPU/int8 com quatro threads e é carregado ao iniciar o servidor, sem capturar áudio. Um lock evita instâncias duplicadas durante a preparação. O áudio capturado a 48 kHz pelo G522 é convertido para 16 kHz para transcrição. A voz SAPI gera WAV local; cancelamento impede a reprodução de uma síntese que terminou após a interrupção.

## Verificação e limites

Uma frase artificial foi sintetizada pela voz Windows em WAV de 22.050 Hz, com cerca de 3,93 s de duração, e transcrita pelo Whisper local. Não houve gravação do microfone, reprodução de som ou envio desse áudio a um serviço externo. A transcrição não foi perfeita: o termo “status” foi reconhecido como “os tatos”. O teste comprova execução local; a precisão com a voz do usuário e a qualidade perceptiva continuam exigindo teste manual.

Os testes automáticos cobrem modelo carregado uma única vez, uso exclusivo dos arquivos preparados, falha sem download quando os pesos faltam, conversão de 48 kHz para 16 kHz e cancelamento de reprodução. Os demais testes de memória, ferramentas, histórico e catálogo Gemini continuam aplicáveis.

Após a correção de escopo, 39 testes Python e 4 JavaScript passaram, assim como `pip check`. O servidor confirmou `provider=gemini`, `tts_provider=offline`, `stt_provider=whisper-local`, Whisper pré-carregado e G522 selecionado; o catálogo Gemini retornou 19 modelos. A comparação do `.env` com o backup anterior à tentativa mostrou somente as duas mudanças de provedor de áudio. Não há Ollama escutando na porta 11434.

As alterações anteriores para raciocínio local foram desfeitas: código e configuração do Hermes/Gemini restaurados, processo Ollama extra encerrado e modelo `qwen3.5:2b` retirado. O `qwen3.5:9b` preexistente e a instalação original do Ollama foram preservados. O runtime portátil, seu ZIP e o log foram retirados do projeto e arquivados em `%LOCALAPPDATA%/JarvisBackups/undo-local-ai-20261015`.

O modelo Gemini estava vazio antes da tentativa de migração e foi preservado assim. Escolha um modelo na lista do painel e salve antes de conversar pela API.

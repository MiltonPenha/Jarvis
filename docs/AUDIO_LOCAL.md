# Voz Qwen em CPU e transcrição local — 15/10/2026

O raciocínio usa **Gemini pela API**, modelo `gemini-3.6-flash`. **Whisper base** transcreve o G522 localmente. A seleção atual de síntese é **Qwen local**, com a amostra da referência **Jarvis (UCM) - Português Brasileiro**, identificador `a5b93aeddcc948c19ea04f0afe9d178c`. É uma recriação de timbre e não uma exportação do modelo vocal da Fish Audio; a semelhança exige avaliação auditiva.

## Qwen local: CPU, sem VRAM

O processo de voz usa somente `CPUExecutionProvider`, com `CUDA_VISIBLE_DEVICES=-1`, oito threads, otimizações ONNX e espera ativa das threads desativada. Não importa PyTorch, não carrega CUDA/DirectML e não recebe credenciais de IA. O tokenizer usa arquivos locais e `trust_remote_code=False`; a rede é bloqueada no trabalhador. As amostras da referência ficam preparadas no disco e não são buscadas a cada fala.

O modelo e o condicionamento da referência são mantidos em cache, liberados após 180 s sem pedidos, ao interromper a fala ou ao encerrar o servidor. São aproximadamente 1,6 GiB de **RAM do sistema**, sem alocação de VRAM pelo motor de voz. Há limite de 3.300 MiB para o trabalhador, reserva de 1,5 GiB de RAM livre, preparação limitada a 45 s e geração limitada a 120 s. Falhas não acionam outro fornecedor/voz automaticamente.

Para preparar novamente, execute `.venv/Scripts/python.exe scripts/setup_qwen_voice.py`. Ele instala as dependências exatas em `.runtime/voice-lab/packages`, valida tamanho/SHA-256 dos modelos, fonte e referência, e preserva todas as preferências. Selecione **JARVIS · Qwen local (CPU, sem GPU)** em Síntese. `JARVIS_QWEN_THREADS=8` é o perfil medido; outros valores entre 1 e 16 podem ter desempenho diferente. A voz local não exige `FISH_API_KEY`.

A fala Qwen usa texto limpo e aproximadamente 220 caracteres, com indicação de que detalhes estão na tela quando reduzido; o texto completo continua no HUD. Enquanto sintetiza, a interface permanece processando; muda para falando quando começa a reprodução. O áudio WAV é mono, 24 kHz. Uma amostra curta levou 7,5–7,7 s para gerar 1,68 s de fala; uma frase de 49 caracteres levou 26,8 s para 3,92 s de fala. A espera não desapareceu. Veja [as medições](VOICE_RESOURCES.md).

## Alternativa online: referência exata do catálogo Fish Audio

1. Crie uma chave em [Fish Audio → API keys](https://fish.audio/app/api-keys).
2. Preencha `FISH_API_KEY=sua_chave` no `.env` local. Aspas simples ou duplas são opcionais para chaves sem espaços. Não envie a chave na conversa ou no painel.
3. Escolha Fish Audio em Síntese, salve e reinicie o JARVIS. O painel informa se a chave está presente, sem expô-la. A presença da chave não significa autenticação já validada. Essa opção ainda não foi validada com geração real por falta de chave.

O cliente chama `POST https://api.fish.audio/v1/tts` com `reference_id` fixo e header `model: s2.1-pro-free`. `FISH_TTS_MODEL` permite outro motor oficial por escolha explícita; valores desconhecidos são recusados localmente, pois o serviço documenta fallback para motor pago quando o header é inválido/ausente. Não há repetição automática de requisição ou troca de voz/motor. A disponibilidade e os limites dependem da conta.

O formato é MP3 mono a 44.100 Hz/128 kbps, velocidade original e latência `balanced`. A fala é limpa e limitada a aproximadamente 700 caracteres antes do envio. O texto da resposta segue para Fish Audio; a gravação do microfone fica no computador e só o texto transcrito segue ao Gemini. Cancelar fecha a requisição pendente e impede reprodução posterior; não garante estorno de processamento já aceito pelo serviço. Uma falha mostra instrução local segura sem publicar corpo de erro/credenciais do fornecedor. O prazo total de síntese é 40 s, leitura de rede 25 s e áudio limitado a 8 MB.

Piper/Faber, Windows/SAPI, Edge e OpenAI permanecem alternativas manuais. Não há fallback automático entre motores de áudio.

## Tom e tratamento

O perfil local opcional Faber pt-BR usa `length_scale=1.18`, variação moderada e volume 0,92, com ritmo mais pausado. A amostra Faber anterior é de outra voz e não comprova a qualidade da voz Fish Audio escolhida.

O prompt do Hermes orienta tratamento respeitoso como **Senhor**, tom suave, calmo e centrado, sem exagero ou repetição do vocativo. A preferência explícita também foi salva e verificada na memória nativa. Pedidos simples devem receber respostas diretas; assuntos que exigem detalhes continuam desenvolvidos.

## Alternativa local: preparação e execução

`scripts/setup_voice.ps1` instala as dependências travadas, prepara Whisper/Piper e salva `tts_provider=piper` e `stt_provider=whisper-local`. Preserva o provedor e modelo da IA, as credenciais, o microfone e demais preferências. O setup baixa Faber de uma revisão fixa de `rhasspy/piper-voices` e confere SHA-256 do ONNX, JSON e model card. Durante fala e transcrição são usados somente arquivos locais; arquivos ausentes produzem erro com instrução de preparação.

Piper usa ONNX Runtime em CPU com duas threads, cache do modelo e locks de carregamento/síntese. A preparação inicial aquece o fonemizador e uma inferência curta, sem reproduzir som. Whisper usa CPU/int8 com quatro threads e é carregado sem ligar o microfone. O áudio a 48 kHz do G522 é convertido para 16 kHz para reconhecimento. A reprodução WAV respeita o cancelamento, inclusive quando uma síntese termina depois da interrupção.

Quando Piper é selecionado manualmente, o texto da resposta é sintetizado no computador. A espera pela API Gemini continua existindo. Com Fish Audio selecionado, há também o tempo de síntese pela internet.

## Evidência e limites

- Na integração Qwen CPU, 57 testes Python e 6 JavaScript passaram. Incluem rejeição de fornecedor GPU, ambiente sem chaves, cancelamento durante EOF do trabalhador, retirada de arquivo parcial, pressão de RAM, cache e preservação de IA/STT/microfone. A geração Qwen real e cancelamento real também foram verificados sem playback. Os cenários Fish continuam usando transporte HTTP controlado, sem geração real no serviço.
- A amostra `.data/validation/jarvis-neural-sample.wav` tem cerca de 5,4 s, 22.050 Hz e 238.124 bytes. Após aquecimento de aproximadamente 5,47 s na preparação, duas sínteses levaram 0,52 s e 0,46 s. São medições de uma frase, sem garantia para todo texto/carga.
- A preferência “Senhor” foi gravada/reaberta na memória nativa e preservada. A referência usada pelo Qwen é fixa; não há troca silenciosa para Faber/Windows.
- No último pedido real observado antes da mudança de voz, o tempo reportado pelo worker Gemini foi 14,05 s, com primeira resposta em 13,99 s. A troca de TTS não elimina esse tempo. Nenhuma nova geração paga foi feita para medir a voz.
- Qualidade da transcrição e avaliação perceptiva dependem da voz do usuário e do ambiente. Um teste anterior com SAPI produziu erro em “status”; não foi apresentado como precisão perfeita.

Os downloads extras da tentativa anterior de IA local foram retirados do projeto; o modelo adicional foi removido e o modelo Ollama preexistente foi preservado. Não há integração Ollama nesta configuração.

## Fontes e licenças

- [API oficial Fish Audio](https://docs.fish.audio/api-reference/endpoint/openapi-v1/text-to-speech) e [voz escolhida](https://fish.audio/pt/app/text-to-speech/?modelId=a5b93aeddcc948c19ea04f0afe9d178c).
- [API Python oficial do Piper](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/API_PYTHON.md), motor GPLv3.
- [Voz Faber e model card](https://huggingface.co/rhasspy/piper-voices/tree/main/pt/pt_BR/faber/medium), dataset declarado CC0. Revisão fixada: `c10ece1aade47bb51c153c893d14e5bf8e5b7117`; origem/checksums em `.data/models/piper/manifest.json`.

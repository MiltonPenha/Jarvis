# Voz neural e transcrição locais — 15/10/2026

O raciocínio usa **Gemini pela API**; o modelo escolhido pelo usuário é `gemini-3.6-flash`. **Piper/Faber** gera a voz neural localmente e **Whisper base** transcreve o G522 no computador. A voz Windows/SAPI continua como alternativa manual. Não há fallback automático entre motores de áudio.

## Tom e tratamento

O perfil Faber pt-BR usa `length_scale=1.18`, variação de áudio moderada e volume 0,92, com ritmo mais pausado. É uma voz neural de catálogo; a semelhança subjetiva com o estilo pedido deve ser avaliada pela amostra, sem promessa de identidade vocal com o personagem.

O prompt do Hermes orienta tratamento respeitoso como **Senhor**, tom suave, calmo e centrado, sem exagero ou repetição do vocativo. A preferência explícita também foi salva e verificada na memória nativa. Pedidos simples devem receber respostas diretas; assuntos que exigem detalhes continuam desenvolvidos.

## Preparação e execução

`scripts/setup_voice.ps1` instala as dependências travadas, prepara Whisper/Piper e salva `tts_provider=piper` e `stt_provider=whisper-local`. Preserva o provedor e modelo da IA, as credenciais, o microfone e demais preferências. O setup baixa Faber de uma revisão fixa de `rhasspy/piper-voices` e confere SHA-256 do ONNX, JSON e model card. Durante fala e transcrição são usados somente arquivos locais; arquivos ausentes produzem erro com instrução de preparação.

Piper usa ONNX Runtime em CPU com duas threads, cache do modelo e locks de carregamento/síntese. A preparação inicial aquece o fonemizador e uma inferência curta, sem reproduzir som. Whisper usa CPU/int8 com quatro threads e é carregado sem ligar o microfone. O áudio a 48 kHz do G522 é convertido para 16 kHz para reconhecimento. A reprodução WAV respeita o cancelamento, inclusive quando uma síntese termina depois da interrupção.

O áudio fica no computador; o texto reconhecido segue ao Gemini como pedido. O texto da resposta retorna para síntese local. Portanto, a espera pela API continua existindo.

## Evidência e limites

- 42 testes Python passaram após a integração neural; `pip check` passou. Incluem carregamento único sem downloads, execução CPU, resampling e preservação de IA/microfone ao escolher Piper.
- A amostra `.data/validation/jarvis-neural-sample.wav` tem cerca de 5,4 s, 22.050 Hz e 238.124 bytes. Após aquecimento de aproximadamente 5,47 s na preparação, duas sínteses levaram 0,52 s e 0,46 s. São medições de uma frase, sem garantia para todo texto/carga.
- A preferência “Senhor” foi gravada/reaberta na memória nativa; o servidor confirmou Gemini, Piper, Whisper, G522 e os dois motores de áudio preparados.
- No último pedido real observado antes da mudança de voz, o tempo reportado pelo worker Gemini foi 14,05 s, com primeira resposta em 13,99 s. A troca de TTS não elimina esse tempo. Nenhuma nova geração paga foi feita para medir a voz.
- Qualidade da transcrição e avaliação perceptiva dependem da voz do usuário e do ambiente. Um teste anterior com SAPI produziu erro em “status”; não foi apresentado como precisão perfeita.

Os downloads extras da tentativa anterior de IA local foram retirados do projeto; o modelo adicional foi removido e o modelo Ollama preexistente foi preservado. Não há integração Ollama nesta configuração.

## Fontes e licenças

- [API Python oficial do Piper](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/API_PYTHON.md), motor GPLv3.
- [Voz Faber e model card](https://huggingface.co/rhasspy/piper-voices/tree/main/pt/pt_BR/faber/medium), dataset declarado CC0. Revisão fixada: `c10ece1aade47bb51c153c893d14e5bf8e5b7117`; origem/checksums em `.data/models/piper/manifest.json`.

# Medição de voz local com outros programas abertos — 15/10/2026

## Resultado e decisão

O Qwen3-TTS 0.6B Base foi testado de verdade, com ONNX INT4, CPU e a amostra pública da referência Fish Audio `a5b93aeddcc948c19ea04f0afe9d178c`. Gerou um WAV válido, mas levou **47,179 s** para uma frase de **1,68 s**. Com os limites usados, não foi considerado adequado para conversa e **não foi ativado no assistente**. Essa conclusão se aplica a esta implementação, hardware, limites e carga; não é um benchmark de todas as implementações Qwen ou de GPU.

Piper/Faber, já instalado, ficou muito mais leve e rápido, mas tem outro timbre. A escolha atual Fish Audio foi preservada para não substituir silenciosamente a voz específica solicitada. Gemini, Whisper, G522, memória e credenciais não foram alterados. Nenhuma API de geração foi chamada, nenhum microfone foi gravado e nenhum áudio foi reproduzido automaticamente.

## Carga e método

Na inspeção inicial, o computador tinha 16 processadores lógicos, CPU média de 48,7%, 5,99 GiB de RAM disponível e RTX 4060 Ti em 99%, com 6.989/8.188 MiB de VRAM ocupados. A carga variou durante os testes; não foi controlada nem foram encerrados programas do usuário.

Cada trabalhador de síntese recebeu afinidade nos dois últimos processadores lógicos disponíveis, prioridade abaixo do normal, duas threads internas, execução ONNX sequencial e apenas `CPUExecutionProvider`. Não foi usado CUDA/DirectML. A rede foi bloqueada no trabalhador de inferência e os arquivos já estavam preparados localmente.

O monitor amostrou a árvore inteira do processo a cada aproximadamente 100 ms, incluindo o lançador do Python do Windows. CPU foi normalizada por 16 processadores lógicos para corresponder à escala de CPU total da máquina. RAM é soma dos working sets da árvore, não tamanho dos pesos nem diferença da RAM total do sistema. Os limites de interrupção foram 2.300 MiB por árvore, menos de 1,5 GiB de RAM livre ou 120 s de duração. Afinidade/prioridade limitam concorrência, mas não garantem ausência de impacto em outros programas.

## Números observados

| Medida | Qwen 0.6B ONNX INT4 | Piper/Faber |
|---|---:|---:|
| Carregamento antes da síntese | 13,292 s | 8,141 s |
| Síntese da primeira frase | 47,179 s | 0,588 s |
| Sínteses seguintes | não repetidas | 0,461 / 0,457 / 0,480 s |
| Duração do áudio | 1,680 s | 3,785–3,947 s |
| Pico de RAM da árvore | 1.597,91 MiB (1,56 GiB) | 210,01 MiB |
| CPU média da árvore, incluindo carga | 10,33% do total | 5,82% do total |
| Pico amostrado de CPU | 13,41% | 13,40% |
| Menor RAM livre durante o teste | 5,46 GiB | 5,98 GiB |
| GPU usada pelo motor de voz | nenhuma; CPU apenas | nenhuma; CPU apenas |

A afinidade em dois processadores lógicos corresponde a cerca de 12,5% da capacidade lógica total. Picos de 13,4% em janelas de 100 ms refletem granularidade dos contadores/intervalos e incluem o lançador. A média inclui importação e carregamento; não deve ser confundida com CPU constante durante a fala. Nas três sínteses Piper já aquecidas, o tempo de CPU somado foi 2,673 s em 1,398 s de relógio, aproximadamente 11,95% da CPU total durante essa geração curta. Durante a reprodução ou inatividade, esses números não se aplicam. O consumo da transcrição Whisper e do servidor não está incluído no consumo do processo de síntese.

As frases são diferentes: Qwen gerou “Às suas ordens, Senhor.”, enquanto Piper gerou “Às suas ordens, Senhor. Estou pronto para ajudar, com calma e atenção.”. A comparação mostra que o Qwen testado foi lento mesmo com menos texto; não é comparação controlada de qualidade entre modelos com duração igual.

O processo Qwen foi encerrado ao fim do teste, liberando seu modelo da memória. Os pesos e dependências ficam isolados em `.runtime/voice-lab`, sem modificar o ambiente principal ou carregar na inicialização do JARVIS. A configuração Fish ativa continua exigindo a chave Fish Audio.

Uma execução negativa com prazo de 1 s foi interrompida em 1,104 s (`time_limit`, código 15 do trabalhador). A inspeção posterior confirmou zero trabalhadores de benchmark restantes e preservação de Gemini `gemini-3.6-flash`, Whisper e seleção Fish Audio pela API do servidor. A verificação de sintaxe Python e `git diff --check` passaram. O motor do produto não foi modificado neste teste.

## Qualidade e evidência

O áudio Qwen tem 24 kHz e 80.684 bytes. Whisper local reconheceu uma aproximação da frase, com erros; isso confirma conteúdo de fala, mas não certifica dicção, identidade vocal ou semelhança com a referência. O reconhecimento da amostra Piper também apresentou erros. A avaliação auditiva continua sendo do usuário; nenhum resultado foi descrito como clone perfeito.

Arquivos locais de evidência:

- `.data/validation/qwen-resources.json`: amostras, fases e consumo do Qwen.
- `.data/validation/piper-resources.json`: quatro sínteses Piper e consumo.
- `.data/validation/voice-resource-transcripts.json`: transcrição local dos áudios gerados.
- `.data/validation/qwen-resource-sample-1.wav`: amostra Qwen gerada.
- `.runtime/voice-lab/assets.json`: origem, revisão, tamanho e SHA-256 dos downloads.

Com os arquivos preparados, repita individualmente (não em paralelo):

```powershell
.\.venv\Scripts\python.exe scripts/benchmark_voice.py --engine qwen --iterations 1
.\.venv\Scripts\python.exe scripts/benchmark_voice.py --engine piper --iterations 4
```

O comando sobrescreve apenas as próprias amostras/relatórios de benchmark; não altera a voz ativa. Os resultados variam com a carga dos demais programas.

Fontes dos modelos: [Qwen3-TTS oficial](https://github.com/QwenLM/Qwen3-TTS), [exportação ONNX utilizada](https://huggingface.co/onnx-community/Qwen3-TTS-12Hz-0.6B-Base/tree/2b18c0a044a190e35f1a907779aa51cda0fb1fff). Pesos ONNX da revisão `2b18c0a044a190e35f1a907779aa51cda0fb1fff`, tokenizer/config originais da revisão `5d83992436eae1d760afd27aff78a71d676296fc`; fonte de inferência SHA-256 `28d2a4ddcda8bbae6ab58b75ebf429541e366a1f50a583a9f8ac1cf58e80c167`. O script usa tokenizer local, sem executar código remoto. Nenhuma velocidade publicitária foi tomada como resultado deste PC.

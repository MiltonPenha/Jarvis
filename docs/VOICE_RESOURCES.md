# Medição de voz local com outros programas abertos — 15/10/2026

## Resultado e decisão

**Atualização após esclarecer a restrição de VRAM:** Qwen CPU foi integrado e selecionado com oito threads. A restrição anterior a dois processadores lógicos deixou de ser necessária. O teste do motor integrado gerou duas frases curtas em 7,652 s e 7,503 s, com pico de 1.658,74 MiB na árvore e média de 26,32% da CPU total (pico 54,11%, incluindo carga). A comparação com 12 threads não trouxe melhora consistente: 8,919/9,041 s, contra 10,470/8,063 s no teste ONNX de oito threads anterior à integração. São execuções com carga externa variável, não um ensaio controlado de escalabilidade.

O perfil integrado usa `ORT_ENABLE_ALL`, sem espera ativa dos pools, oito threads, cache do modelo e do condicionamento da referência. Nenhum fornecedor de GPU é permitido; CPU é confirmado na inicialização do trabalhador. Há cerca de 1,5 GiB residentes em cache, liberados após três minutos sem uso, ao cancelar ou ao encerrar. Uma amostra maior, de 49 caracteres, levou 26,836 s para 3,92 s de áudio. Portanto, execução local sem VRAM está validada, mas a latência continua relevante. O teste dessa amostra coincidiu com outros testes do projeto, além dos programas do usuário.

No relatório integrado, `summary` e as amostras periódicas abrangem toda a árvore, incluindo o processo do modelo. Os eventos `ready`/`synthesis` são emitidos pelo chamador e seus campos locais de RAM/tempo de CPU não incluem os filhos; não devem ser usados como consumo do modelo. A API do servidor reiniciado confirmou `qwen-local` pronto, CPU/oito threads e 1.513,4 MiB residentes no trabalhador, preservando Gemini `gemini-3.6-flash`, Whisper e G522. O reinício foi feito sem abrir outra janela do JARVIS.

Cancelamento real foi reconhecido em 0,234 s desde o agendamento de uma interrupção de 0,2 s; o arquivo parcial foi removido e o trabalhador fechado. A corrida entre cancelamento e EOF foi coberta por teste de regressão. 57 testes Python e 6 JavaScript passaram. Nenhum áudio foi reproduzido ou microfone gravado. Gemini e Whisper foram preservados. Amostra: `.data/validation/jarvis-qwen-cpu.wav`; evidência real: `.data/validation/qwen-cpu-integration.json`; perfil integrado: `.data/validation/qwen-cpu_integrated-resources.json`.

Os resultados abaixo registram o **teste inicial com duas threads**, anterior à integração.

O Qwen3-TTS 0.6B Base foi testado de verdade, com ONNX INT4, CPU e a amostra pública da referência Fish Audio `a5b93aeddcc948c19ea04f0afe9d178c`. Gerou um WAV válido, mas levou **47,179 s** para uma frase de **1,68 s**. Com aqueles limites, inicialmente não foi considerado adequado para conversa e não foi ativado nessa etapa. Essa conclusão se aplica àquela configuração; o perfil atual está descrito acima.

Piper/Faber, já instalado, ficou muito mais leve e rápido, mas tem outro timbre. Na etapa inicial a escolha Fish Audio foi preservada. Gemini, Whisper, G522, memória e credenciais não foram alterados. Nenhuma API de geração foi chamada, nenhum microfone foi gravado e nenhum áudio foi reproduzido automaticamente.

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

O processo Qwen daquele teste foi encerrado ao fim, liberando seu modelo da memória. Os pesos e dependências ficam isolados em `.runtime/voice-lab`, sem modificar o ambiente principal. No perfil integrado atual, são carregados na inicialização quando Qwen é a voz selecionada e liberados depois de ociosidade; a opção Fish continua exigindo sua própria chave.

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

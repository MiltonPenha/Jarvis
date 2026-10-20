# Voz → tarefa → YouTube — 18/10/2026

## Diagnóstico comprovado

O ledger contém dois pedidos reais:

- `Morote Jarls, abre o YouTube e toca uma música do Dancing Roses.` O plano continha somente `browser_open`; o restante do objetivo foi omitido. A gramática reconhecia `toque`, mas não `toca`, e não removia esse vocativo inicial.
- `Pô, noite, Jarnes. Abra o YouTube e toque no meu música do Guns and Roses.` O plano abriu o site, tentou `media(resume)` sem player e só depois faria `play_music`. A execução parou corretamente na ferramenta sem alvo, mas o plano estava errado.

Na configuração persistida, o provedor era e permanece `local-cpu`, modelo `qwen3:1.7b`. O aviso de interpretação na CPU correspondia a essa escolha; não foi constatada troca silenciosa de Gemini/OpenAI para CPU. Pedidos diretamente reconhecidos não precisam de inferência, qualquer que seja o provedor salvo. Pedidos novos continuam usando a seleção salva e, para nuvem, o `AIAgent` oficial do Hermes.

O G522 WASAPI está selecionado e usa 48 kHz porque esse modo não aceita 16 kHz diretamente. Uma primeira tentativa de medição automática capturou só 1,8 s; não é possível distinguir retrospectivamente atraso para começar a falar de corte da frase. Na medição seguinte, o usuário aguardou um bipe, houve uma janela fixa de 14 s e o Whisper base reconheceu a frase completa, incluindo `Guns and Roses`, em 0,53 s de transcrição. Pico absoluto 0,0996, saturação zero, perdas de bloco zero. Isso comprova que dispositivo/transcritor funcionam nessa amostra; não comprova ausência de falhas na captura automática nem explica toda transcrição antiga, cujos áudios não foram guardados.

Havia ainda uma inconsistência de estado: o serviço gravava `completed` antes de sintetizar/falar a resposta, mantendo o lock até a fala terminar. O pedido seguinte encontrava tarefa/fala ocupada apesar da conclusão exibida. A limpeza do arquivo temporário da voz também podia impedir a liberação do lock se o arquivo estivesse bloqueado.

## Correções

- `command_text.py` mantém o texto original e normaliza apenas o prefixo conversacional. Correspondência aproximada fica limitada a vocativos curtos anteriores a uma ação explícita, com proteção para negação/condição e conteúdo de notas. Não há substituição de artistas.
- A gramática aceita variações imperativas (`toca`, `abre`, `coloca`) e remove construções de determinantes antes do substantivo música. A consulta extraída permanece separada do texto original. Referências como “dessa banda” usam a consulta da sessão; sem contexto, pede o artista. “Outra dessa banda” usa a próxima faixa.
- Iniciar/pesquisar usa `play_music(query)`; retomar usa `media(resume)`. O preparo de planos remove o resume indevido de um pedido de início. O executor comum também corrige esse desvio antes da admissão/checkpoint. O Hermes usa o mesmo executor e verifica a capacidade musical ainda pendente ao finalizar um turno que só abriu o site, dentro dos limites e sem repetir efeitos incertos.
- A busca exige correspondência suficiente com título/canal, ignorando conectivos. Uma consulta incerta não é convertida para uma banda conhecida; sem evidência suficiente, pede confirmação. A reprodução continua exigindo vídeo correto, avanço do tempo e ausência de pausa/anúncio/erro, informando mudo e volume.
- O início `LISTENING` só é emitido depois de abrir o stream. A conversão para 16 kHz usa o resampler do PyAV já instalado, com filtro contra aliasing. Português continua `pt`; modelo/dispositivo não foram substituídos. Contexto de vocabulário e beam ficam configuráveis.
- A tarefa só termina depois de encerrar a fala ou seu timeout. Callbacks carregam tarefa ou ID da captura. Eventos antigos não substituem tarefas novas no HUD. Cleanup de voz libera o lock mesmo quando não consegue apagar o temporário.
- Novo pedido de microfone pode aguardar com aviso (padrão) ou interromper a tarefa da mesma conversa, conforme a preferência `voice_busy_policy`. Aguarde o indicador ESCUTANDO antes de falar. Interromper continua disponível. Só se envia uma transcrição final por enunciado; capturas canceladas não enviam resultados atrasados. O modo contínuo reconhece o vocativo no prefixo, aguarda a própria fala e informa quando não houve ativação.

## Instrumentação e parâmetros

`GET /api/tasks/{id}` inclui `input`: origem, transcrição original, texto normalizado, captura, provedor/modelo configurados, provedor efetivo, intenção/argumentos e tempo de interpretação. As ferramentas guardam duração, resultado, aba e URL; a tarefa guarda estado e motivo final. `.data/logs/voice-events.jsonl` liga a captura à tarefa e tem rotação. Não registra chaves. A configuração pública informa somente presença das credenciais.

Variáveis opcionais no `.env.example`:

| Variável | Padrão | Efeito |
| --- | --- | --- |
| `JARVIS_VAD_THRESHOLD` | `0.004` | limiar de RMS; preservado |
| `JARVIS_VOICE_SILENCE_SECONDS` | `1.2` | silêncio para terminar; tolera pausas naturais maiores |
| `JARVIS_VOICE_MAX_SECONDS` | `20` | limite da fala |
| `JARVIS_VOICE_PREROLL_SECONDS` | `0.3` | áudio anterior à detecção |
| `JARVIS_WHISPER_BEAM_SIZE` | `3` | busca do decodificador, mesmo modelo CPU/int8 |
| `JARVIS_WHISPER_CONTEXT` | pt-BR/Jarvis/aplicativos | vocabulário opcional, sem artista fixado |
| `JARVIS_SPEECH_TIMEOUT` | `45` | limite para gerar a voz; reprodução recebe a duração do áudio mais 5 s |
| `JARVIS_AUDIO_DIAGNOSTICS_HOURS` | `0` | áudio bruto desativado; opção limitada a 24 h, limpeza na próxima captura |

As duas medições reais desta etapa não conservaram gravações. Permanecem somente textos/medições. Se uma pausa natural superar o limite configurado, a captura pode terminar antes do restante; aumente o parâmetro com base na amostra medida e repita o teste. Não foi alterado ganho do Windows ou limiar de sensibilidade.

Parâmetros do transcritor: [fonte oficial faster-whisper](https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/transcribe.py). A troca de resampling foi verificada com sinal de 12 kHz a 48 kHz: o filtro evita que a redução para 16 kHz introduza esse componente na banda da fala.

## Testes

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -v
node --test tests/test_model_selectors.cjs
.venv/Scripts/python.exe scripts/validate_chrome_session.py
.venv/Scripts/python.exe scripts/validate_voice_chain.py --session ID_DA_CONVERSA
```

Os testes de voz usam o WebSocket real, emitem bipe somente após o stream abrir, aguardam fala humana e exigem uma tarefa única, login/reprodução confirmados e liberação de mic/fala/tarefa. Nenhum mock substitui a confirmação real do player. Os testes unitários cobrem transcrições observadas, variações de artista, contexto ausente, plano resume indevido, pausas configuradas, resampling, limpeza com falha, espera de microfone, cancelamento e eventos atrasados. Os scripts de validação falham se não conseguirem confirmar o resultado; o relatório não deve ser interpretado como aprovação sem `passed: true`.

Relatórios: `.data/voice-fixed-window-validation.json`, `.data/voice-chain-validation.json` e `.data/chrome-session-validation.json`. O primeiro mede apenas captura/transcrição controlada; os outros dependem de Chrome autorizado e um teste final executado no ambiente atual.

## Correção de artista e corte da resposta — 18/10/2026

O pedido `Gunner Rose` chegou com esse nome na transcrição. Na correção seguinte, porém, o Whisper reconheceu `guns and roses` corretamente e o planejador repetiu a consulta anterior. Correções explícitas de artista/título agora têm precedência sobre planos do modelo e usam o nome literal informado. Uma busca musical não confirmada permanece como objetivo pendente da conversa, inclusive após reiniciar o backend; uma reprodução confirmada encerra essa pendência.

Se a busca não encontrar correspondência lexical suficiente, o modelo local pode avaliar nomes de canais realmente observados. A consulta é curta (até 60 tokens de saída, 30 s), na CPU. O modelo só pode escolher IDs fornecidos, com proximidade de nome e suporte nos resultados; incerteza pede confirmação. Não há tabela fixa de artistas, geração livre de um nome substituto ou fallback pago. Uma interpretação aceita provoca nova busca e continua exigindo reprodução verificada. O mecanismo atual resolve nomes de artistas/canais; não garante correção de qualquer título ou enunciado.

O limite antigo de 45 s incluía geração e reprodução. O registro real mostrou 35,2 s de geração para 104 caracteres, consumindo quase todo o prazo antes de falar. Agora o prazo de geração é separado do prazo de reprodução, calculado pelo áudio real. Respostas operacionais faladas usam a mensagem curta do último resultado, evitando narrar referências DOM e listas de links; o resultado completo permanece na tela.

Validação real da voz aprovada, através do watchdog do serviço: 26,955 s de geração, áudio de 6,72 s e reprodução observada de 7,119 s, concluída sem corte. A resposta desse ensaio é uma frase fixa, não uma interpretação de IA. Relatório: `.data/speech-completion-validation.json`. O teste automatizado cobre também geração perto do limite seguida de reprodução integral, cancelamento e timeout de geração.

`scripts/validate_music_resolution.py` usa inferência real com candidatos controlados, sem alegar navegação real. Na medição, `Gunner Rose` → `Guns N' Roses` levou 3,35 s, e `Lincoln Park` → `Linkin Park`, 1,378 s; um nome sem relação foi recusado. VRAM observada: zero. Relatório: `.data/music-resolution-validation.json`. O teste de navegador com conteúdo interceptado cobre nova busca, nome efetivo e avanço real do player, mas não substitui o ensaio no YouTube autenticado.

## Objetivo musical, correções e encerramento — 19/10/2026

O ledger confirmou três problemas separados: `happy do Minecraft do Taus` já veio assim do Whisper, mas a extração preservou Minecraft; a seleção antiga rejeitou o vídeo pela cobertura literal mínima de 70%; uma correção posterior entrou no planejador genérico, que descartou Minecraft e abriu outra aba. O áudio histórico não foi conservado, portanto não há evidência para atribuir esses dois registros a corte do microfone. As falhas não passavam pela síntese, que existia apenas no caminho de sucesso.

Whisper base permanece em português, CPU/int8, sem aproveitar texto de capturas anteriores. O beam padrão passou a 3 e o silêncio final a 1,2 s. `hotwords` e o contexto recebem apenas o objetivo e o título já confirmados da conversa, sem tabela de artistas. A transcrição bruta nunca é reescrita. Compatibilidade fonética é avaliada contra resultados observados e registrada como correção fundamentada separada; não existe substituição global de Happy por Rap.

O encerramento do serviço centraliza sucesso, falha, esclarecimento e cancelamento explícito. `input.final_feedback` e `speech_result` distinguem entrega, desativação, erro, timeout e supressão por correção posterior. O áudio reserva o microfone até drenar a saída; a captura manual pode começar durante uma busca, enquanto a captura contínua aguarda a tarefa. Nenhuma delas grava durante a voz do JARVIS. Cancelamentos de geração e callbacks atrasados são cercados pelo identificador da tarefa.

A captura humana seguinte trouxe `Jarvis, toque rápido Minecraft do Tauz`, com 4,4 s, nenhum overflow/saturação e transcrição em 0,761 s. O modelo retirou `rápido`; a validação detectou a perda e pediu esclarecimento, sem pesquisar. Esse caso motivou uma única reextração orientada pela rejeição quando faltam palavras e comparação fonética com trechos observados de duas/três palavras. A comparação de palavras unidas exige um termo distintivo exato e artista sustentado; nunca troca `rápido` por uma expressão fixa. Acentos do texto original são preservados no registro da correção. Esse primeiro ensaio não aprovou a cadeia completa.

Os scripts existentes foram ampliados: `validate_music_request.py --scenario minecraft --voice --session ID` usa texto com inferência real, Chrome de produção e saída de voz; `validate_voice_chain.py --session ID` exige uma fala humana após o bipe, captura única, Minecraft preservado, reprodução verificada e entrega real da síntese. Seus relatórios são, respectivamente, `.data/music-flow-live.json` e `.data/voice-chain-validation.json`. Cada resultado depende de `passed: true`; um ensaio com texto não comprova o microfone.

A validação final no G522/Chrome/saída real passou (`voice-probe-57cdaa5aacdb4d0c914ec264434fb068`). Captura 4,3 s, 48 kHz WASAPI, zero overflow/saturação, transcrição 0,532 s: `Jarvis, toque rápido do Minecraft do TAUS.` A transcrição foi mantida; a extração literal conservou todos os termos e a escolha por resultados observados fundamentou rápido → Rap do e TAUS → Tauz, sem exigir campos opcionais de título/artista quando a atribuição é sustentada pela própria consulta e pelo canal. O vídeo `LVMHYzVS9Y4`, `Rap do Minecraft | Tauz RapGame 06`, iniciou sem mudo/anúncio/erro e teve avanço verificado. Houve uma única ferramenta e uma única transcrição; três inferências CPU, zero API/VRAM. Geração de voz 24,059 s, áudio 4,4 s, saída concluída em 28,58 s; total do ensaio 62,206 s. Relatório `.data/voice-chain-validation.json`, `passed: true`, com locks liberados.

O reconhecimento ainda pode errar nomes/palavras. A recuperação exige evidência suficiente; isso não é garantia de transcrição perfeita. RAM/commit do Windows insuficiente pode impedir o carregamento e a voz CPU continua sendo a principal parcela de atraso. A configuração de voz aprovada e o modelo local não foram substituídos.

O ajuste posterior de seleção musical foi validado separadamente em `.data/music-selection-live.json`: três transcrições históricas reproduzidas como texto, Chrome autenticado e IA CPU real, uma busca por pedido, ID selecionado reproduzido e avanço confirmado por status. A resposta falada do último pedido foi entregue em 16,65 s (13,599 s de geração + áudio de 2,96 s). Não houve nova gravação no G522 nesse ensaio; ele valida interpretação/DOM/player e saída de voz, preservando a configuração aprovada.

Em 19/10/2026, o teste no Chrome autenticado também passou: `.data/music-interpretation-live.json`, `passed: true`. O pedido com `Gunner Rose` acionou uma inferência real de 4,509 s, zero VRAM/API paga, escolheu o canal observado `Guns N' Roses` e iniciou `Welcome To The Jungle`. O vídeo `o1tj2zJ2Wvg` avançou de 0,55 s para 1,750 s na mesma aba, sem pausa, anúncio, mudo ou erro. A execução completa levou 28,292 s. Esse ensaio usa entrada de texto reproduzindo a transcrição problemática, com fala temporariamente desligada e restaurada ao final; não equivale a uma nova captura humana de ponta a ponta.

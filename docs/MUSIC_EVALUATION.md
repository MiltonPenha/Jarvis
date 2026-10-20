# Avaliação musical reproduzível

Esta bateria mede o código e os modelos atuais; **executar testes não é treinamento**. Não ajusta pesos, não baixa outro modelo e não muda automaticamente provedores, microfone ou qualidade da voz. Qwen3:1.7b e Whisper base/int8 permanecem na CPU. O relatório registra hashes dos fontes, corpus e manifestos do modelo, sem chaves do `.env`.

## Corpus e reserva

`evaluations/music/development.json` contém 14 pedidos e seis cenários de seleção. `holdout.json` contém 12 pedidos e seis cenários, com outras obras/artistas. A validação do corpus rejeita IDs duplicados e obras/artistas compartilhados entre as divisões de texto. Os resultados de seleção são **dados controlados**, incluindo contraexemplos intencionais; não são uma declaração sobre o catálogo real do YouTube. Os IDs desses cartões são fictícios e nunca devem ser abertos.

Há português, títulos ingleses, espanhóis, franceses, alemães, japoneses e coreanos, siglas, números, nomes incomuns, saudações, pedidos indiretos, palavras que podem ser título ou instrução, falta de conteúdo e negação. Isso não comprova domínio de todos esses idiomas: a instrução de voz continua em português, conforme o produto atual.

Congele os JSONs antes da linha de base. Use somente detalhes de desenvolvimento para orientar correções. `--seal-holdout` grava os resultados individuais da reserva, mas não os exibe; abra-os apenas depois de congelar os ajustes. É uma reserva operacional, não um teste cego independente: quem criou os casos conhece seus conteúdos. Uma vez que resultados da reserva, inclusive métricas agregadas, orientarem novos ajustes, aposente essa versão como reserva e crie outra com novas obras/artistas. Não reclassifique falhas como sucessos nem altere os rótulos para melhorar a comparação. A comparação recusa mudanças no corpus ou modelo.

## Etapas e critérios

| Etapa | Entrada e ambiente | Medida |
|---|---|---|
| Transcrição | WAV com referência humana confirmada; Whisper CPU real | WER, CER, recall literal dos termos do conteúdo, latência, dispositivo e hash do áudio |
| Intenção | Texto de referência; extração Qwen CPU real | Encaminhamento musical e decisão tocar/esclarecer/não tocar; registra a decisão completa |
| Consulta | Saída da extração | Conteúdo comparado ao rótulo independente; aceita variação dos conectivos de/do/da/dos/das, mas não apaga instruções, dígitos, letras únicas ou erros de nomes |
| Seleção | Cartões controlados; seletor Qwen CPU real | ID válido do conjunto esperado ou abstenção/ambiguidade esperada; primeira posição não é o oráculo |
| Reprodução | Player simulado para contratos; Chrome real na integração | ID correto, avanço sem anúncio/erro/pausa; falhas técnicas sem pesquisar novamente nem anunciar sucesso |
| Fala | Contratos com saída simulada; uma entrega real na integração | Mensagem de conclusão/falha/esclarecimento uma vez e diagnóstico de entrega/falha; qualidade subjetiva de timbre não é inferida por `delivered` |

Transcrição não depende de a música tocar. Extração não depende da transcrição: a bateria de texto usa a referência correta para isolar essa etapa. Seleção usa consulta/objetivo rotulados, sem depender da extração. A integração mede a composição real dessas etapas. Um sucesso posterior não oculta uma falha anterior. Gravações podem ser comparadas à bateria de texto para localizar perda no reconhecimento.

Os limites iniciais para transcrição são WER ≤ 20% e recall de conteúdo = 100%; são critérios de avaliação, não probabilidades de confiança do modelo. WER pode ser maior que 100% por inserções. Há contagem de erros/palavras para agregar WER pelo corpus, não média indevida por frase. Casos humanos e sintéticos ficam em grupos separados. Seis amostras de uma pessoa não sustentam estimativas populacionais de precisão. Os percentis de duração em baterias pequenas são descritivos; a integração também inclui rede/anúncios/carregamento.

`passed`, `failed`, `blocked` e `skipped` são estados distintos. Falta de áudio, referência não confirmada ou runtime indisponível não conta como aprovação nem desaparece do denominador de cobertura. A taxa de aprovação tem como denominador somente casos avaliados; sempre veja a cobertura ao lado. O código de saída 1 indica falha avaliada; 2 indica dependência bloqueada. Não se deve apresentar um contrato com player/áudio simulado como reprodução/fala real.

## Gravações com o G522

Os ensaios antigos não conservaram áudio humano. As amostras de voz em `.data/validation` são de síntese e não demonstram reconhecimento do usuário. Esta bateria guarda gravações intencionais em `.data/evaluation/music/recordings`, fora do Git. Elas não usam a retenção temporária de diagnóstico e continuam disponíveis para repetição; apague os WAVs/manifesto quando não quiser mais conservá-los.

Primeiro pare somente o backend ocioso, usando o encerramento habitual/autenticado. Fechar a janela do HUD não necessariamente encerra o backend. O script recusa captura e inferência offline com o backend ativo, evitando disputa do microfone e duas cópias dos modelos em RAM. Não encerre o Chrome pessoal nem outros programas. O modo offline não inicia o servidor automaticamente.

Execute uma gravação quando o usuário estiver pronto; ele deve falar a frase exibida depois do bipe. Usa `AudioManager.record_phrase` e o microfone selecionado pelo JARVIS, sem alterar o padrão do Windows:

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_music.py record --case dev-minecraft
.\.venv\Scripts\python.exe scripts/evaluate_music.py record --case dev-queen
.\.venv\Scripts\python.exe scripts/evaluate_music.py record --case dev-pra-mim
.\.venv\Scripts\python.exe scripts/evaluate_music.py record --case hold-numeric
.\.venv\Scripts\python.exe scripts/evaluate_music.py record --case hold-accent
.\.venv\Scripts\python.exe scripts/evaluate_music.py record --case hold-french
```

O manifesto guarda taxa, dispositivo/hostapi, overflow, duração, hash e texto solicitado. A captura desta bateria usa pausa de 1,5 s e limite de 16 s para obter comandos completos; não comprova isoladamente a segmentação da captura de produção, cujo limite é configurável. Esse texto começa como referência **não verificada**: não presuma que a pessoa leu exatamente a frase. Confirme com ela ou escute e anote o que realmente foi dito. Só então:

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_music.py confirm-reference --manifest .data/evaluation/music/recordings/manifest.json --ids ID1 ID2 --confirmed-by user
# Para corrigir uma referência de uma única gravação:
.\.venv\Scripts\python.exe scripts/evaluate_music.py confirm-reference --manifest .data/evaluation/music/recordings/manifest.json --ids ID1 --reference 'Texto realmente falado' --confirmed-by user
```

O replay nunca fornece a frase esperada nem o nome correto como hotwords. Apenas `observed_context`, se anotado como contexto realmente disponível antes do pedido, pode ser usado; o padrão é vazio. Gravações externas podem ser descritas no mesmo manifesto com `source: human` ou `synthetic`, caminho relativo, SHA-256 e referência confirmada. Áudio sintético pode complementar, mas não preencher a cobertura humana. Registrar som é uma ação explícita do comando `record`; os comandos `run` apenas leem arquivos.

## Linha de base e repetição offline

Os relatórios são imutáveis por caminho: escolha outro nome para nova execução. Não execute estes comandos com o servidor ativo. A inferência usa o runtime privado existente do projeto, iniciado e encerrado pelo avaliador, sem compartilhar nem terminar o Ollama pessoal.

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_music.py run --phase before --split all --seal-holdout --recordings .data/evaluation/music/recordings/manifest.json --output .data/evaluation/music/RUN/before.json
# Analise somente os detalhes de development; corrija causas gerais no código.
# Congele o código antes de abrir os resultados da reserva.
.\.venv\Scripts\python.exe scripts/evaluate_music.py run --phase after --split all --recordings .data/evaluation/music/recordings/manifest.json --output .data/evaluation/music/RUN/after.json
.\.venv\Scripts\python.exe scripts/evaluate_music.py compare --before .data/evaluation/music/RUN/before.json --after .data/evaluation/music/RUN/after.json --output .data/evaluation/music/RUN/comparison.json
```

Para executar uma etapa: `--modes text`, `selection`, `contracts` ou `stt`, ou uma lista separada por vírgulas. Texto e seleção executam a IA real; os testes unitários do avaliador verificam os próprios cálculos/contratos com simulação. Se não houver mudança de runtime entre duas passagens, o relatório registra isso: não invente uma melhoria e considere a variabilidade da execução.

## Integração menor no computador

Reinicie o backend com `run_jarvis.py --no-browser`, aguarde ficar pronto e conecte o Chrome pelo controlador habitual. O usuário pode precisar aceitar a autorização nativa. A bateria não cria outro cliente CDP nem perfil; usa a API autenticada existente e a mesma aba controlada.

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_music.py live --phase before --session ID_DA_CONVERSA --output .data/evaluation/music/RUN/before-live.json
.\.venv\Scripts\python.exe scripts/evaluate_music.py live --phase after --session ID_DA_CONVERSA --output .data/evaluation/music/RUN/after-live.json
.\.venv\Scripts\python.exe scripts/evaluate_music.py compare --before .data/evaluation/music/RUN/before-live.json --after .data/evaluation/music/RUN/after-live.json --output .data/evaluation/music/RUN/comparison-live.json
```

São três músicas do desenvolvimento, com comandos de texto, IA real, resultados reais, ID selecionado e duas observações do player avançando. Repetir o mesmo ID de evento não pode disparar nova busca. O verificador também exige termos observados de título/artista, em vez de confiar apenas na autoavaliação da IA. Só o último pedido usa voz real; as outras saídas ficam explicitamente `skipped`, e a configuração original de fala é restaurada. A música da aba será trocada durante esse ensaio. Falhas terminais são registradas e os outros casos continuam; um efeito ainda em execução interrompe a bateria. A reprodução e os dados do YouTube variam com anúncio, sessão, catálogo e rede; preserve o JSON bruto com as observações para investigar divergências.

O critério primário desta integração é reprodução verificada sem outro turno. Uma pergunta apropriada entre versões diferentes não satisfaz esse critério; registre o motivo e não a descreva automaticamente como interpretação errada. O fluxo posterior pode ser verificado separadamente com `scripts/validate_music_request.py --scenario confirmation --session ID --voice --report CAMINHO_NOVO.json`, quando existir uma proposta pendente observada. A frase de aceitação desse script é uma entrada programada do teste, não fala humana; reprodução e saída de voz continuam reais. Não some esse ensaio complementar aos acertos automáticos da bateria congelada.

## Interpretação dos resultados

Agrupe falhas por etapa e fenômeno (número, nome, pontuação, limite de conteúdo, falta de evidência, navegação, áudio), não por música. Uma correção deve atuar nesse mecanismo e ser testada com outros termos e contraexemplos. Não acrescente aliases de artistas ou uma resposta decorada para acertar o corpus. Não reduza automaticamente os critérios para aumentar a taxa. Não há treinamento/retreinamento automático nem troca de pesos neste fluxo; uma proposta futura precisa mostrar falhas persistentes, volume/diversidade do corpus, custo/latência e comparação justa antes de qualquer decisão.

# Feedback visual e voz local — 19/10/2026

O modelo de linguagem continua **Qwen3:1.7b**, e a voz salva continua **Qwen local**. Nenhum peso foi alterado. Piper já estava instalado e foi reaproveitado; não houve download de outra voz nem instalação de outro servidor.

## Causas comprovadas

- A preparação admitia uma resposta maior, mas o caminho Qwen aplicava outro limite de **220 caracteres**. O terminal podia conter informação que nunca chegava à síntese. Agora a preparação é compartilhada e os trechos completos, de até 180 caracteres, formam um WAV único. A resposta muito longa ainda tem o limite explícito de apresentação de 700 caracteres, com aviso dos detalhes na tela.
- A geração do áudio emitia `PROCESSING`, misturando interpretação e síntese na interface. Agora eventos `speech` distinguem fila, geração, reprodução e conclusão. O temporizador de geração se renova por trecho; a reprodução tem seu próprio prazo e um limite total de segurança.
- Resultados ambíguos de música eram tratados como erro de execução. Os estágios estruturados de esclarecimento agora encerram a tarefa sem executar outro efeito e mostram **Aguardando informação**. Falha de navegação/modelo/reprodução continua falha.
- Cada atualização de progresso virava mais uma mensagem no terminal. Agora atualiza uma linha estável. Eventos atrasados de ferramentas, resposta, pedido e voz não podem substituir o pedido ativo. A resposta final tem uma única apresentação.
- O diagnóstico final guardava a resposta visual no lugar do texto realmente preparado para falar. Agora preserva o texto falado e as métricas de entrega.
- As amostras analisadas não apresentaram saturação digital nem troca indevida da taxa de amostragem. Isso **não** comprova naturalidade ou ausência de defeitos audíveis no headset.

## Interface e coordenação

O HUD destaca pedido reconhecido, fase do pedido, fase da voz, conteúdo observado e estado independente do player. Resultados encontrados, seleção, abertura, confirmação e esclarecimento têm apresentações distintas. Só `verified=true` **e** `playback_confirmed=true` apresentam reprodução confirmada. Abertura de pasta/aplicativo enviada ao Windows é identificada como **solicitada ao Windows**, sem inventar confirmação de janela aberta.

O estado da mídia vem de uma leitura do player já vinculado, no mesmo controlador Playwright. A consulta não abre abas nem reconecta o Chrome. Enquanto o controlador está ocupado, a tela indica atualização pendente e preserva o contexto; não anuncia uma observação nova. Leituras simultâneas compartilham a consulta pendente, sem misturar abas de conversas diferentes.

A transcrição original aparece no painel principal. Eventos parciais e finais têm rótulos diferentes; o Whisper atual continua entregando o resultado final, sem transcrição parcial inventada. A retomada da conexão recupera os dados persistidos da tarefa. Não há reconstrução do histórico a cada progresso.

As animações passaram de 160 para 96 partículas, com limite aproximado de 20 quadros/s em atividade, 10 em repouso e 1 com redução de movimento. Abas ocultas não desenham. Os painéis permitem rolagem em telas pequenas; os testes verificaram 1440×900, 1000×800 e 390×844. Na tela pequena, pedido e conversa vêm antes da telemetria, com reator compacto e campo de texto que não empurra o botão para fora do painel. As fontes têm fallback local e não dependem de uma chamada ao Google Fonts.

A prévia usa a mesma fila, trava de saída, reserva do microfone e interrupção das respostas normais. Não usa o modelo de linguagem nem executa o conteúdo da frase. O histórico identifica as frases como prévias. Não há redução automática do volume da música. Um erro de voz mantém o texto e registra sua causa; não existe troca silenciosa para serviço externo.

## Texto e áudio

A preparação remove código, links e marcações técnicas, preserva nomes e números de títulos, e expande porcentagens e horários acompanhados de contexto. Exemplo: `47%` → `quarenta e sete por cento`; `para 18:30` → `para dezoito horas e trinta minutos`. Não há dicionário de substituições de nomes de artistas.

Os trechos Qwen são frases/unidades pontuadas, não tokens. Toda a geração termina antes de tocar o WAV, evitando intervalos de inferência entre trechos; isso mantém continuidade, mas **não reduz a espera inicial de respostas longas**. Há 120 ms entre trechos, com formato nativo validado. Qwen gera/reproduz em 24 kHz; Faber em 22,05 kHz. Os dados são verificados como não vazios e finitos. A saída permanece exclusiva até a drenagem do dispositivo, e o microfone fica reservado para não reconhecer a própria resposta.

## Comparação medida

Corpus idêntico de seis pedidos de saída em `evaluations/voice_feedback.json`: confirmação, falha, pergunta, números, nomes PT/EN e resposta longa. A linha de base reproduz o preparo/limite e a configuração anteriores. Nos casos de números e texto longo, o texto preparado muda intencionalmente; não são comparações de WAVs com texto idêntico. Há uma execução por frase/configuração, sem pretensão estatística.

| Configuração | Geração da primeira frase, incluindo carga | Demais frases | Resposta longa: geração / áudio | Pico RSS da árvore |
| --- | ---: | ---: | ---: | ---: |
| Qwen anterior | 24,240 s | 14,064–50,862 s | 50,862 s / 13,520 s, com corte | 1.783 MiB |
| Qwen ajustada | 23,916 s | 14,533–85,214 s | 85,214 s / 20,080 s, completa | 1.735 MiB |
| Piper Faber anterior, escala 1,18 | 3,116 s | 0,166–1,012 s | 1,012 s / 20,584 s | 263 MiB |
| Piper Faber, ritmo padrão 1,0 | 3,055 s | 0,160–0,930 s | 0,930 s / 18,727 s | 259 MiB |

Os picos incluem processo de avaliação e seus filhos, não apenas pesos. Nenhuma das 24 amostras principais apresentou valores não finitos ou amostras no teto digital. A primeira carga afeta a latência. A Qwen não recebeu ajuste de timbre ou aceleração; a resposta longa ficou mais lenta porque agora entrega o texto completo.

“Completa” identifica o texto entregue a todos os trechos e os frames concatenados, sem o corte oculto anterior. Ainda falta conferir por escuta a realização de cada palavra pelo modelo de voz.

No ensaio longo, a geração anterior de 50,862 s também ultrapassava o watchdog de geração de 45 s. O novo orçamento por trecho impede que uma sequência saudável de trechos seja interrompida só pelo tempo acumulado de inferência; travamento de um trecho ainda interrompe a saída.

Medição suplementar de CPU no computador de 16 processadores lógicos, com outros processos abertos: a mesma confirmação Qwen consumiu 137,266 → 133,500 segundos de CPU, equivalentes a cerca de 28,1 → 28,8% da capacidade total durante os respectivos 30,548 → 28,935 segundos de geração. O Piper ajustado consumiu cerca de 11,6–13,4% durante as inferências aquecidas. Não são percentuais de um único núcleo nem limites garantidos de carga. A Qwen usa até oito threads de inferência; Piper, duas. As sessões usam somente `CPUExecutionProvider`, sem CUDA/VRAM para inferência. A reprodução e os demais aplicativos têm seu consumo próprio.

As sínteses principais e suplementares rodaram com conexões externas bloqueadas **no processo de avaliação**, mantendo apenas IPC loopback para o asyncio do Windows. O worker Qwen também bloqueia suas conexões e usa assets locais. Não foi necessário desligar a rede do computador.

## Piper: documentação e vozes

A [API oficial](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/API_PYTHON.md) documenta síntese WAV, ajuste de duração, áudio por trechos e CUDA opcional. O projeto usa ONNX Runtime CPU, sem a opção CUDA. A implementação existente foi mantida, com perfis configuráveis de duração: `original` preserva a escala configurada no ambiente, e `natural` usa o ritmo padrão 1,0. Esse nome de perfil identifica ritmo; não certifica naturalidade.

O [catálogo oficial](https://huggingface.co/rhasspy/piper-voices/blob/main/voices.json) lista Cadu, Faber e Jeff em qualidade medium/22,05 kHz, e Edresson em low/16 kHz. Apenas **Faber**, já instalada, foi sintetizada nesta etapa. Cadu/Jeff/Edresson foram examinadas pelo catálogo e model cards, sem comparação de escuta ou benchmark. Não há base para declarar uma delas mais natural.

O software atual Piper usa [GPL v3](https://github.com/OHF-Voice/piper1-gpl/blob/main/COPYING). O [repositório das vozes](https://huggingface.co/rhasspy/piper-voices/blob/main/README.md) declara MIT; os model cards de [Faber](https://huggingface.co/rhasspy/piper-voices/blob/main/pt/pt_BR/faber/medium/MODEL_CARD), Cadu e Jeff identificam **CC0 para seus datasets**, enquanto Edresson identifica **CC BY 4.0**. São declarações distintas do software e dos dados de voz. A Faber tem um falante pt-BR e modelo de aproximadamente 63 MB.

Piper teve custo e latência menores neste PC. A naturalidade, a pronúncia de inglês, o timbre e a preferência em relação à Qwen ainda exigem escuta humana. Por isso a voz padrão não foi trocada. A serialização evita a síntese simultânea ao atendimento de outra tarefa, mas os modelos residentes podem coexistir na RAM com Whisper e o modelo de linguagem.

## Como ouvir e repetir

Recarregue o HUD e abra **Configurações → Ouvir e comparar sem alterar a voz salva**. Escolha uma frase e Qwen, Faber pausada ou Faber no ritmo padrão. **Ouvir frase** não muda a configuração salva. **Parar comparação** interrompe somente a tarefa de prévia. Para escolher a voz definitiva, selecione Síntese e Ritmo do Piper e use **Salvar configurações**. A Qwen continua disponível para retorno.

Comandos de avaliação, executados com a saída de produção ociosa:

```powershell
.venv\Scripts\python.exe scripts/evaluate_voice_feedback.py --phase before --engine qwen-local
.venv\Scripts\python.exe scripts/evaluate_voice_feedback.py --phase after --engine qwen-local
.venv\Scripts\python.exe scripts/evaluate_voice_feedback.py --phase before --engine piper
.venv\Scripts\python.exe scripts/evaluate_voice_feedback.py --phase after --engine piper
.venv\Scripts\python.exe scripts/validate_feedback_output.py
.venv\Scripts\python.exe scripts/validate_speech_completion.py
.venv\Scripts\python.exe scripts/validate_feedback_hud.py
```

Os dois scripts de validação de saída **tocam áudio real**, com falas de teste fixas; nenhum usa microfone, busca música ou agenda o alarme mencionado na frase. O script do HUD usa Chrome headless com perfil temporário e eventos simulados, sem se conectar ao Chrome pessoal. A medição suplementar aceita `--case confirmation --tag=-cpu-check`.

Relatórios, WAVs e capturas ficam em `.data/evaluation/voice-feedback/`. O resultado da conclusão Qwen está em `.data/speech-completion-validation.json`. Os testes e as capturas permanecem reutilizáveis.

## O que foi executado e o que permanece pendente

- **Automatizado:** 226 testes na suíte Python completa e 16 testes JavaScript aprovados, incluindo extração/seleção musical, confirmação, controles de volume, abertura de aplicativos, cancelamento, ausência de duplicação e prevenção de autoescuta com dispositivos simulados. Depois do ajuste final para emitir “falando” somente após iniciar a saída, 56 testes focais de voz/feedback/música passaram novamente; falha ao iniciar o dispositivo não emite reprodução iniciada. Testes específicos novos cobrem preparo/chunks, evidência de confirmação, esclarecimento, prévia e observação de mídia sem conexão.
- **Síntese real offline:** seis frases antes/depois em Qwen e Piper, mais medições suplementares de CPU. Sem microfone e sem serviços de voz externos.
- **Reprodução real Qwen:** 37,959 s de geração, 6,720 s de arquivo; o controlador observou 6,966 s entre início da fala e conclusão. Sem corte pelo watchdog. Resposta fixa de validação, não resposta de um pedido musical real.
- **Reprodução/interrupção reais Piper:** interrupção durante o áudio em aproximadamente 0,194 s; ambas as travas liberadas; nova resposta de 3,077 s reproduzida por completo. As frases e a correção são fixtures.
- **Prévia real na interface:** Piper, frase com 47% e 18:30; 3,128 s de geração e 6,072 s de áudio, conclusão registrada. Modelo de linguagem e voz salva preservados.
- **Visual real:** inspeção do HUD e configurações no navegador local; renderização desktop/mobile e regressão de eventos controlados em Chrome headless. Capturas do ensaio identificam seus dados como simulados, sem fingir reprodução no YouTube.
- **Pendente de escuta:** preferência de timbre, entonação, pronúncia e continuidade percebida no G522. Métricas não substituem essa avaliação. Não foi solicitada nova gravação do microfone.
- **Não refeito nesta etapa:** música/volume no YouTube pessoal após reiniciar o backend, nem comprovação visual de abertura de um aplicativo real. A sessão do Chrome precisa ser reconectada com sua autorização nativa para esse ensaio. As rotinas de efeito foram preservadas e cobertas por regressão, mas isso não equivale a um novo ensaio real nesses aplicativos.

Durante a construção dos testes novos, um import antecipado inicializou caminhos de produção antes do ambiente isolado da suíte. Isso causou falhas e alterou a seleção salva do microfone. O import foi movido para a inicialização do teste; o G522 WASAPI foi restaurado e a suíte completa passou com isolamento correto. Esse problema de teste não foi atribuído à voz ou ao usuário.

Seis registros de tarefa criados por essa execução incorreta também foram identificados por ID, sessão, texto e instante de criação; foram arquivados em `.data/evaluation/voice-feedback/test-isolation-recovery.json` e retirados da fila de produção. As conversas e tarefas do usuário foram preservadas.

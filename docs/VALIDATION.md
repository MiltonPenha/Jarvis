# Validação — 15/10/2026

## Áudio local

A configuração atual usa voz neural Piper/Faber e Whisper local, mantendo o Gemini para a IA. O usuário recebeu uma resposta real com `gemini-3.6-flash`. A amostra neural está em `.data/validation/jarvis-neural-sample.wav`, com medições em `.data/validation/neural-voice.json`; 42 testes Python passaram. A síntese/transcrição Windows anterior permanece como evidência histórica em `voice-local.json`; apresentou erro no termo “status”. Detalhes em [AUDIO_LOCAL.md](AUDIO_LOCAL.md).

## Correção posterior: reabrir a janela

O iniciador encerrava sem abrir o HUD quando já havia um servidor ativo. Agora identifica a instância JARVIS pelo `/health` e reabre uma janela de aplicativo Chrome/Edge sem criar outro servidor. Três testes de regressão em `tests/test_launcher.py` passaram. A execução real de `start_jarvis.bat` com a instância ativa retornou normalmente; o endpoint respondeu HTTP 200 e foi identificada uma janela JARVIS do Chrome. O `.env` atualizado foi carregado ao reiniciar a instância ociosa. Esses testes são adicionais aos 26 da implementação inicial descritos abaixo.

Não há resultados de geração real OpenAI/Gemini aprovados. Na auditoria inicial, as credenciais herdadas foram recusadas; posteriormente, a chave Gemini atual consultou o catálogo com sucesso. Testes de transporte/serviço com respostas controladas estão identificados abaixo e não representam desempenho ou qualidade de um modelo de nuvem.

## Verificações executadas

| Verificação | Resultado e alcance |
|---|---|
| Projeto original executável | HTTP 200 para UI, telemetria, memória e comando de status antes da migração |
| Instalação Hermes oficial | PM concluiu, revisão `7bda2a...`; import de `run_agent.AIAgent` aprovado |
| Roteamento real de configuração | Resolver oficial selecionou `openai-api` → `api.openai.com/v1`, `gemini` → `generativelanguage.googleapis.com/v1beta`; não é teste de geração |
| Autenticação nos catálogos reais | Auditoria inicial: OpenAI HTTP 401 e Gemini HTTP 403. Estado posterior: catálogo Gemini HTTP 200, 19 modelos de conversa visíveis no HUD |
| Suíte automática | **36 testes Python e 4 JavaScript aprovados** após a revisão de limpeza; a saída inicial de 26 testes continua arquivada em `.data/validation/tests.txt` |
| Dependências próprias | `pip check`: nenhuma dependência quebrada |
| Compilação e scripts web | `compileall` e `node --check` dos dois scripts da UI aprovados |
| Hermes → ferramenta → resultado → resposta | AIAgent real contra servidor local de respostas controladas: arquivo de teste gravado, resultado `verified`, ID da chamada preservado e mensagens persistidas |
| Ponte worker → host | Leitura real de DOCX no executor do host através do protocolo do worker; texto e origem verificados |
| PDF e qualidade da evidência | PDF com texto extraído e página de origem; suíte vazia não conta como teste aprovado; compilação isolada não autoriza uma skill confiável |
| Busca web real | DDGS executado pelo worker/host retornou fontes; vault de validação escrito e consultado por essa mesma ponte, evidência em `.data/validation/tools/results.json` |
| Memória nativa | Preferência adicionada; outro processo leu; outro corrigiu; outro excluiu; última leitura confirmou exclusão |
| Obsidian | Vault temporário: gravação, busca sem acentos, atualização por hash, reabertura e remoção do índice após apagar a fonte |
| Arquivos e teste de código | Arquivo e unittest criados em workspace temporário; teste executado com saída OK e código 0; escrita concorrente com hash errado recusada |
| Falhas e duplicação | IDs repetidos reutilizados; checkpoint de escrita não reexecutado; efeito incerto bloqueado; falha de ferramenta não pode produzir resposta de sucesso integral |
| Cancelamento, fallback e orçamento | Testes de serviço com runtime controlado: cancelamento, timeout, limite diário, fallback visível antes de efeitos e bloqueado após efeito |
| Controle de contexto | Teste corta somente turnos completos e mantém associação chamada/resultado; não foi ensaio prolongado de produção |
| Proteção de acesso | Cookie, origem e Host incorretos recusados; credenciais não são editáveis via settings |
| Voz real, sem microfone | Edge sintetizou 21.024 bytes MP3, 24 kHz, 3,5 s; Google Web Speech transcreveu “Jarvis diga o status do sistema” |
| Cancelamento de áudio | Síntese controlada cancelada antes de finalizar: nenhuma chamada de playback ocorreu |

O teste de transcrição foi feito por `scripts/validate_voice.py` somente com frase artificial, sem reprodução e sem gravar o microfone. Evidência local em `.data/validation/voice.json` e `.data/validation/voice.mp3`. Posteriormente, uma abertura física de 250 ms confirmou sinal no G522 a 48 kHz, sem salvar/enviar esse áudio; o teste da fala do usuário segue pendente.

## Cobertura dos 18 fluxos solicitados

1. Conversa principal real: **aguarda escolha do modelo e validação de geração**.
2. OpenAI e Gemini reais: **catálogo Gemini aprovado com a chave atual; geração não aprovada**. A recusa anterior do catálogo Gemini é evidência histórica.
3. Troca de provedor mantendo estado: mesma SessionDB/MemoryStore por construção e testes de persistência; **troca com dois provedores reais pendente**.
4. Chamada e interpretação de ferramenta: **aprovada com Hermes real e modelo controlado localmente**.
5. Entrada/saída de voz: síntese/transcrição artificial e abertura física do G522 **aprovadas**; reconhecimento da fala do usuário e escuta perceptiva **pendentes**.
6. Interrupção/cancelamento: **testes de código aprovados**; teste físico de áudio **pendente**.
7. Preferência após reiniciar: **aprovada em processos separados**.
8. Corrigir/excluir preferência: **aprovado**.
9. Buscar/atualizar nota Obsidian: **aprovado em vault de teste**.
10. Documento com fonte: **DOCX aprovado pela ponte real e PDF com texto/página aprovado**; documentos complexos, imagens/OCR pendentes.
11. Alteração de arquivo verificada: **aprovada**.
12. Código e teste: **unittest real aprovado no workspace de teste**; investigação autônoma com modelo real pendente.
13. Ferramenta falha sem sucesso falso: **aprovado no serviço**.
14. Retomada: **testes de checkpoints aprovados**; tarefas extensas reais pendentes.
15. Ausência de execução duplicada: **teste de pedido/checkpoint aprovado**; efeitos incertos bloqueiam, não há garantia distribuída absoluta.
16. Autenticação/limites/timeout: erros reais de autenticação + cenários controlados de serviço; **429 real não provocado**.
17. Orçamentos: **teste de limite de admissão aprovado**; limite diário é suave durante uma tarefa e não é limite da conta.
18. Uso prolongado: contexto por turnos é limitado, workers terminam por tarefa e conexões SQLite são fechadas; **ensaio prolongado de produção ainda não executado**.

## Consumo observado

- Nenhuma geração bem-sucedida nos provedores pagos principais; o catálogo Gemini atual foi consultado com sucesso, sem gerar texto.
- Os tokens do teste de modelo controlado são números de fixture e ficam somente nos dados temporários de teste, nunca como consumo real.
- Uma síntese Edge e uma transcrição Google Web Speech de frase artificial foram concluídas. Nenhuma estimativa monetária foi inventada para esses serviços.
- Não foram configurados preços de modelos. O painel mantém custo desconhecido quando faltam preços/data; custos de voz não estão somados aos tokens do modelo.

## Procedimento manual de áudio

1. Inicie JARVIS e escolha a entrada em **CONFIGURAÇÕES → Microfone**. O microfone inicia desligado. A preferência salva vence `JARVIS_INPUT_DEVICE`; saída opcional continua em `JARVIS_OUTPUT_DEVICE`.
2. Em ambiente silencioso, clique no microfone e diga uma frase curta. Observe escutando → processando e confira a transcrição na interface. Com credencial inválida, o erro do modelo deve aparecer sem travar o HUD.
3. Com chave/modelo válidos, peça um resumo curto e avalie articulação, português, pausas e volume. Compare voz Edge e offline; avalie OpenAI somente após configurar seu modelo de áudio e orçamento.
4. Durante a fala, use **DESLIGAR MICROFONE / PARAR VOZ**; o áudio deve parar. **INTERROMPER** também cancela a tarefa. Se a síntese ainda estiver na rede, ela deve ser descartada quando chegar.
5. Ative escuta contínua e diga “Jarvis, que horas são?”. Deixe o assistente falar e confirme que não surge novo pedido com a própria resposta. Uma frase sem a palavra de ativação não deve iniciar tarefa.
6. Repita com ruído moderado. Ajuste `JARVIS_VAD_THRESHOLD` no backend se necessário. O VAD atual usa energia/silêncio; não é um detector neural de fala nem oferece interrupção por voz em duplex completo.
7. Desative a escuta, feche e reabra a aba; confirme que não há captura automática e que o histórico permanece acessível.

## Correção do microfone G522 — 15/10/2026

O padrão de entrada era o Wireless Controller, enquanto o usuário usa o G522 sem fio. A preferência local agora seleciona `Windows WASAPI::Microfone (G522 LIGHTSPEED - Wireless Mode)` por identificador de API/nome, preservado quando o índice muda. O dispositivo rejeitou 16 kHz e aceitou sua frequência nativa de 48 kHz. Uma abertura física de 250 ms recebeu 12.000 amostras, sem overflow; o áudio foi descartado, sem gravação em arquivo ou envio para transcrição.

Há seleção de entrada no painel, diagnóstico de fala detectada e mensagens distintas para ausência de sinal e transcrição sem palavras. A sensibilidade padrão passou de 0,015 para 0,004 RMS; um `JARVIS_VAD_THRESHOLD` explícito continua prevalecendo. Os cinco testes novos cobrem seleção independente do padrão do Windows/índice, fallback para frequência nativa, fala de baixa amplitude com término por silêncio, frequência repassada à transcrição e validação/persistência pela API. Reconhecimento real da voz do usuário permanece pendente de seu teste no HUD.

Após a correção, `unittest discover -s tests -v` passou os 34 testes em 16,821 s. Python e JavaScript passaram na verificação de sintaxe. O servidor reiniciado com `--no-browser` respondeu online e confirmou pela API o G522 salvo/selecionado e a presença do seletor no HUD.

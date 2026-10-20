# Ferramentas reutilizáveis do JARVIS — 15/10/2026

A interface, G522, Whisper e voz Qwen aprovados foram preservados. O controle anterior por teclas globais foi retirado, assim como `music_player.py`, cujo papel passou para o adaptador compartilhado de mídia. Não há código específico para Google + YouTube + Guns N’ Roses, nem normalização especial desse artista.

## Fluxo implementado

1. Voz e texto entram no mesmo `AssistantService`, com fila serializada e o ledger SQLite existente.
2. Intenções claras viram parâmetros. Pausa, retomada, volume e consulta de faixa não consultam modelos, inclusive quando Gemini/OpenAI estão selecionados ou sem crédito.
3. Uma gramática de sequência pode combinar comandos individualmente reconhecidos, preservando a ordem explícita. Por exemplo, abrir um site, abrir outro e tocar um artista usa três chamadas independentes. Se alguma cláusula não for reconhecida, o pedido inteiro vai ao planejador, sem executar apenas uma parte.
4. No modo local, o Qwen retorna um plano JSON limitado. O plano inteiro passa por tipagem/validação antes do primeiro efeito. As ferramentas podem consultar a IA local sobre opções observadas, como artista e recomendações musicais, sem criar outro agente ou ciclo autônomo. O resultado de cada ferramenta determina se a próxima etapa pode ocorrer. Referências dependentes da leitura sem um alvo claro exigem esclarecimento; esse modo não promete resolver qualquer página desconhecida.
5. Na nuvem, permanece o `AIAgent` oficial do Hermes, com seu registro, histórico, ciclo de ferramentas, interrupção e orçamento de iterações. O checkout oficial não foi modificado. Ele recebe os mesmos contratos e executor do modo local. Testamos a integração com um provedor HTTP simulado; nenhuma geração paga foi realizada nesta etapa.
6. Confirmações operacionais vêm dos resultados observados das ferramentas. Abrir aplicativo é uma solicitação enviada ao Windows; reprodução exige avanço real da mídia, sem anúncio ativo. Resultados não verificados interrompem a sequência.

## Contratos e contexto

`core/tool_registry.py` é o catálogo central: descrição, campos, tipos, campos obrigatórios, enums, limites e handler opcional. O schema Hermes e o catálogo do interpretador CPU são derivados dele. `ToolService` continua sendo a fronteira comum de validação, permissões, cancelamento, limites e checkpoints.

- Navegador: abrir URL, pesquisar, consultar estado/texto/elementos, preencher, clicar em referências observadas, voltar, rolar, pesquisar em campo, localizar/selecionar abas próprias e aguardar texto, elemento, carregamento ou avanço do player.
- Sistema: aplicativos já permitidos; consultar/ajustar volume e mudo pelo **Windows Core Audio**, sem teclas de alternância.
- Mídia: HTML audio/video no navegador próprio, com adaptador YouTube para pesquisa, fila e confirmação; pausar, retomar, parar, próxima/anterior quando há fila/destino observado, e consultar título/origem/estado.
- Permanecem tempo, projetos, anotações, lembretes/alarmes, Obsidian e as ferramentas anteriores do Hermes.

O contexto operacional é pequeno, em RAM e separado por sessão: aplicativo, aba, identidade da mídia, tarefa, última ação e resultado compacto. IDs de abas são gerados pelo navegador próprio. Fechar a aba invalida a referência; não redireciona uma pausa para outro player. Mudança externa de faixa exige consultar o estado ou selecionar a aba. Com múltiplos players sem alvo conhecido, o assistente solicita a seleção. Selecionar uma aba com player único estabelece o alvo. Reiniciar servidor/navegador exige novo vínculo; handles antigos não são persistidos.

Navegar para outro site preserva a aba da música. Elementos só podem ser selecionados por referências observadas ou nomes únicos; IDs de uma aba não servem em outra. Campos de senha/arquivo e envios arbitrários continuam manuais. Conteúdo externo não concede permissões, não cria ferramentas e não é executado como código.

## Comandos para testar

Inicie com `start_jarvis.bat` ou `.venv/Scripts/python.exe run_jarvis.py`. Use a mesma conversa para os comandos subsequentes.

```text
Abra o Google, entre no YouTube e toque uma música do Guns and Roses
Aumente um pouco o som
Diminua para 30%
Pause a música
Continue
Passe para a próxima
Volte para a faixa anterior
Qual música está tocando?
Silencie a música
Tire o mudo
Coloque o volume do sistema em 40%
Qual o volume do sistema?
Abra https://www.python.org e leia a página
Liste as abas
Selecione a aba <ID retornado>
```

O volume padrão é **do player**, preservando o volume do Windows e a voz do assistente. Use “do sistema” explicitamente para o Windows. “Para 10%” define o destino 10, mesmo com “aumente/diminua”. “Aumente 10%” e “diminua em 10%” somam/subtraem pontos percentuais. “Dobre” multiplica por 2; “reduza pela metade” multiplica por 0,5; “aumente em 50% do volume atual” multiplica por 1,5. “Coloque pela metade” define 50%.

O incremento sem quantidade ou de “um pouco” é `JARVIS_VOLUME_STEP=5`; o mínimo audível é `JARVIS_MIN_AUDIBLE_VOLUME=1`. Reinicie após alterar essas variáveis. Um único cálculo em `volume_control.py`, compartilhado por HTML/YouTube e Windows Core Audio, lê o estado real, calcula, arredonda metade para cima, aplica no máximo uma vez e verifica nível/mute. Valores são limitados a 0–100%, com mínimo audível nas reduções. Silêncio exige “mute/silencie” ou destino zero explícito. Ajustar para nível positivo remove o mute. Dúvidas de quantidade/relação pedem esclarecimento.

O contrato usa `mode=absolute/relative/multiply/mute/unmute/status`, com `value` numérico (fator fracionário em multiply). Interpretação e cálculo são separados da aplicação. Um pedido simples de volume é revalidado tanto no plano quanto na admissão da ferramenta, impedindo que o modelo converta destino explícito em incremento ou duplique um único ajuste. O ledger registra texto recebido, operação, alvo/aba, nível/mute anterior, destino e estado observado em `input.volume_change` e no resultado de cada ferramenta.

Ensaio no Chrome autenticado em 19/10/2026: `scripts/validate_volume.py --session ID_DA_CONVERSA` confirmou o caso 48→10 e sua repetição, deltas, fatores, mute, mínimo 1% e zero, restaurando o nível anterior e a fala. O Windows foi somente consultado. Relatório `.data/volume-live-validation.json`, `passed: true`. Esse ensaio usa texto equivalente à transcrição, sem nova captura de microfone. Após reinício, um player pode ser recuperado pelo vídeo confirmado da mesma conversa apenas se a aba for única e o player atual confirmar a identidade; isso não navega nem reinicia a faixa.

Pedidos novos/ambíguos usam o provedor escolhido: Qwen CPU ou API via Hermes. O modo exclusivamente local não troca para nuvem. Sites, tempo e YouTube continuam dependendo de internet, mesmo sem API de IA. Falta de chave/crédito não impede os comandos diretos. Não são gerados scripts por comando; novos procedimentos não alteram código ou pesos automaticamente.

## Limites e repetição

- Até `JARVIS_MAX_STEPS` chamadas por tarefa (padrão 6); planos locais têm teto de 6 mesmo se esse valor aumentar.
- Tempo total `JARVIS_TASK_TIMEOUT` (120 s); navegação tem limite de 18 s, ferramentas comuns do navegador 45 s, mídia 75 s e espera observável 8 s. Cancelamento impede etapas seguintes; um efeito já enviado precisa ser conferido.
- Local: contexto de 4096 tokens e até 600 tokens gerados; entrada/prompt compactos, uma inferência e zero fallback pago. Nuvem: saída por chamada `JARVIS_MAX_OUTPUT_TOKENS` (1500), histórico até o menor entre `JARVIS_MAX_CONTEXT_CHARS` e 6000 caracteres em turnos completos, além da memória e ferramentas pertinentes do Hermes.
- `JARVIS_MAX_TASK_TOKENS=24000`: teto **flexível**, baseado no uso reportado. Interrompe novas ferramentas/chamadas após cruzar o limite; uma requisição já em curso pode ultrapassá-lo. Limites diários existentes permanecem. Tokens/latência são registrados quando disponíveis; preço sem tabela configurada fica desconhecido.
- Nova tentativa automática apenas para navegação após fechamento da janela, uma vez. Clique, troca de faixa e volume relativo nunca são reenviados cegamente.
- O plano local admitido fica no ledger da tarefa. Retomá-lo mantém ordem e IDs das etapas, reaproveitando checkpoints; não pede ao modelo um plano diferente. Duas etapas explicitamente distintas podem ter os mesmos argumentos. Um checkpoint incerto/falho bloqueia retomada automática.
- No Hermes, argumentos iguais na mesma tarefa têm deduplicação conservadora. Para pedir outra troca igual, envie um novo comando; não se presume que uma repetição do provedor seja uma segunda ordem humana.

## Validação nesta máquina

Ensaio real, Chrome oculto e silenciado, perfil temporário, sem anexar abas pessoais:

- Formulação nova “Visite o endereço https://example.com; em seguida mostre o texto da página”: Qwen produziu duas ferramentas, página aberta/lida; 1 chamada local, 1512 tokens de entrada e 32 de saída. Primeira inferência do ensaio: 16,67 s, **0 bytes de VRAM reportados pelo modelo**.
- Google → YouTube → busca/reprodução: três checkpoints, zero inferências. Tocou “Welcome To The Jungle”; confirmou avanço do player sem anúncio. Sequência em cerca de 23,91 s, incluindo rede/carregamento.
- Volume em 30%, pausa, retomada, próxima (“Patience”), consulta e anterior, preservando volume. Pausa/volume/status em aproximadamente 0,10–0,16 s, retomada 0,37 s, próxima 2,75 s. Esses tempos não incluem captura, transcrição ou síntese de voz.
- Abriu outra aba e pausou a faixa original corretamente.
- Core Audio real: consultou 80%, reduziu para 79%, verificou e restaurou 80%, preservando o mudo.

Relatório: `.data/tools-validation.json`. Repetição: `.venv/Scripts/python.exe scripts/validate_operational_tools.py`. Ele usa o modelo CPU e internet; não usa Gemini/OpenAI. Feche uma inferência local em andamento antes do ensaio, pois a porta privada tem um único proprietário.

A suíte final passou em **91 testes Python e 6 testes JavaScript**. Pelo servidor reiniciado, consultas de volume do Windows, abas e status concluíram sem inferência; seis mensagens de histórico foram recuperadas e as configurações de áudio foram conferidas/restauradas. Relatório adicional: `.data/tools-server-validation.json`.

Regressões automatizadas usam Chrome real com páginas/áudio interceptados e respostas de modelo simuladas: linguagem, tipos, plano desconhecido, falha de observação, contexto fechado/alterado, múltiplos players, referências por aba, volume/sistema, cancelamento, orçamento e deduplicação/retomada. Execute:

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -v
node --test tests/test_model_selectors.cjs
```

## Adicionar uma ferramenta

Registre um novo contrato com campos tipados e um handler `módulo:função` em `tool_registry.py`. A função recebe `args`, `cancelled` e `context`; retorna dados, `verified`, `message` e `error` quando necessário. Verifique o efeito real antes de marcar `verified=True`. Marque `effect=True` para checkpoint e `local=True` se puder entrar no catálogo CPU.

O schema, catálogo e executor comum incorporam o registro no próximo início do servidor. Argumentos novos podem ir no objeto `arguments` do plano; não exigem outro roteador, ledger ou loop. Adicione caminho direto somente se houver uma intenção frequente e inequívoca; ele deve produzir a chamada normalizada para o mesmo handler. Não é necessário criar uma frase ou um script para cada uso.

## Limitações atuais

O controlador agora também usa a sessão habitual do Chrome por CDP autorizado: veja [CHROME.md](CHROME.md). Spotify ainda precisa de adaptador próprio. HTML com múltiplos players na mesma aba exige seleção de uma reprodução única. No YouTube, próxima usa a fila/playlist quando disponível e as recomendações quando não há próxima faixa; pedidos explícitos de sugestões ou artista usam as recomendações. Anterior depende da fila conhecida. Não há busca global automática nesses pedidos de continuação. Autoplay, anúncios, cookies, CAPTCHA, login, indisponibilidade e mudanças no site podem impedir a confirmação; não são contornados silenciosamente. O modelo pequeno pode errar planos novos; a validação bloqueia ferramentas/argumentos inválidos, mas não garante compreensão universal. A qualidade da voz e do microfone exige o teste falado do usuário. Os ensaios antigos abaixo usavam perfil isolado/silenciado; a validação atual usa o Chrome habitual autenticado.

## Extração de pedidos para buscar e tocar

Novos pedidos musicais passam por `core/music_intent.py` no Qwen CPU, inclusive quando o roteamento reconhece um atalho ou há outro provedor selecionado. O modelo recebe a frase completa e retorna ação (`search_and_play`, `clarify` ou `other`), serviço e trechos literais do conteúdo. O código copia esses trechos do original, em ordem, para formar a consulta. Não pede ao modelo para inventar uma grafia, nem depende de remover o primeiro verbo. O helper legado `music_request` permanece como pista de roteamento/compatibilidade; não é autoridade para a busca final desses pedidos.

Exemplos: “Toca pra mim a música TAUZ MADARA” → `TAUZ MADARA`; “Quero ouvir Razões e Emoções do NX Zero” → `Razões e Emoções NX Zero`; “Toque a música ‘Pra Mim’” → `Pra Mim`. Aspas e limites de conteúdo protegem títulos como “Toca”, “Música Para Mim” e “Outra Deles”. Campos e trechos são validados, nomes são copiados com a grafia/capitalização original, conteúdo relevante não pode sumir, e resíduos de instrução fora do título são recusados. Modelo indisponível, conteúdo ausente ou interpretação não confirmada não geram busca; o assistente informa o problema ou pede a música.

A intenção validada é aplicada antes de salvar o plano, novamente na admissão e no controlador de reprodução. Esses limites impedem que um plano posterior substitua a consulta pela frase original. Planos retomados reutilizam a interpretação admitida. Pausa, volume e sugestões continuam nos caminhos próprios, sem esta inferência adicional. A correção fonética é outra fase: receber `TAUS MADARA` não autoriza a extração a trocar para `TAUZ MADARA`; o resolvedor existente só pode propor alterações com evidência observada.

Diagnóstico por tarefa: `input.original_transcription`, `normalized_text`, `music_intent` (ação/trechos/serviço/query/uso do modelo), `intent` (chamadas admitidas), `music_search_queries` e `final_search_query`. As últimas consultas são registradas no ponto em que o adaptador entrega o termo à navegação de busca, incluindo eventual nova busca fundamentada por resolução fonética. A interpretação do pedido e a resolução de nomes permanecem identificáveis separadamente.

`tests/test_music_intent.py` usa decisões e navegador simulados. `scripts/validate_music_intent.py` executa a IA CPU real, sem microfone/navegador; `scripts/validate_music_request.py --session <conversa>` testa texto equivalente a fala na API e confirma reprodução no Chrome autorizado. Relatórios: `.data/music-intent-model-validation.json` e `.data/music-request-live.json`. O último teste desativa temporariamente a fala e restaura a configuração ao terminar.

## Continuação e seleção contextual de músicas

`music_goal` guarda ação, consulta literal, título/artista quando identificáveis, serviço e vínculo observável da aba. A IA local interpreta uma correção como alteração de campos; “É rap, não happy” troca apenas esse termo e preserva Minecraft e artista. Uma reformulação completa é extraída novamente do texto novo. Campos incertos pedem esclarecimento. Uma nova tentativa invalida a anterior antes de entrar na fila; operações substituídas não podem clicar nem confirmar por voz depois da correção.

A busca inicial usa `music_resolution.select_result` sobre IDs, títulos, canais, posição e duração realmente lidos no YouTube. Evidência independente exige todos os termos essenciais, considera fonética e autoria do canal, exclui tipos incompatíveis e limita o modelo aos candidatos observados suficientemente sustentados. Uma diferença pequena entre faixas não equivalentes exige confirmação, mesmo com confiança alta da IA. A evidência de canal do artista evita favorecer outro upload apenas por escrever literalmente uma palavra transcrita errada. Nenhuma URL vem livremente do modelo.

Cada pedido aceito faz uma busca. A leitura da página pode ser repetida por até 10 segundos para aguardar cartões estáveis, sem navegar novamente ou retirar conectivos para repetir a mesma consulta. A aba controlada é reaproveitada mesmo quando a tentativa anterior parou nos resultados. Referência perdida é recuperada por URL/consulta ou último vídeo confirmado; múltiplas abas sem vínculo exigem seleção. Navegação, leitura, escolha e reprodução têm estágios próprios. O sucesso exige ID escolhido, avanço do tempo e ausência de anúncio/erro. Um timeout de navegação após chegar à URL esperada segue para a leitura/verificação dessa etapa; não reinicia a pesquisa.

O diagnóstico preserva `original_transcription`, `normalized_text`, `music_intent`, `music_goal`, `music_search_queries`, `final_search_query`, `music_selection` (candidatos/evidências/decisão) e `transcription_corrections`. `music_pipeline` vincula a tarefa à consulta, snapshots de leitura, seleção, abertura, verificação e resposta final. Cada leitura captura título, canal e URL no mesmo cartão, com URL/documento, quantidade de cartões incompletos e carregamento. Leitura incompleta, ausência explícita de resultados, falta de correspondência e ambiguidade possuem estágios distintos. A consulta original e o conteúdo resolvido por evidência continuam distinguíveis. Volume e recomendações mantêm seus adaptadores existentes.

Uma extração recusada por omitir conteúdo pode ser refeita uma vez pela mesma IA, com a rejeição como feedback; não existe fallback para uma consulta inventada. Palavras reconhecidas juntas podem ser comparadas a dois/três termos adjacentes de um título observado, mas somente com apoio de um termo distintivo exato e do artista. Essa evidência permanece separada da transcrição bruta.

Os limites literais de título/artista fornecidos pela própria IA podem reparar uma introdução indevida em `content_spans`, passando novamente pela validação de aspas, nomes e conteúdo omitido. Sem limites válidos, há no máximo uma reextração. Títulos protegidos com “Música” continuam preservados. A seleção mantém dígitos e reconhece representações numéricas equivalentes (7/Seven), espaços em nomes e grafias fonéticas com apoio contextual; exige evidência para todos os termos essenciais. As relações e posições originais ficam registradas, sem alterar a transcrição ou pesquisar uma grafia inventada.

Publicações de uma obra podem ser agrupadas por título observado e crédito independente comum, mesmo em canais de gravadora/artista diferentes. Versões live/remix/acústica continuam distintas. Todos os candidatos próximos são avaliados para detectar uma terceira obra ambígua; a posição só auxilia entre publicações já sustentadas. O ID aceito pela IA é o ID executado. Ensaios controlados incluem DOM real com conteúdo simulado em `tests/test_tools_architecture.py`; `scripts/validate_music_request.py --scenario selection --session ID --voice` verifica os pedidos históricos na sessão de produção, sem nova gravação de microfone. Relatório: `.data/music-selection-live.json`.

## Confirmação de uma escolha musical

Uma pergunta específica (“você quis dizer [título]?”) guarda `music_goal.confirmation`: ID da proposta, vídeo/título/canal observados, consulta, URL/aba da pesquisa, conversa, tarefa de origem e horário. A confirmação curta (“é isso Jarvis, exatamente esta música”, “sim”, “essa mesma”) produz `media(check="confirm_music", query=ID_DA_PROPOSTA)`. Não é outra chamada `play_music`: não há nova busca, interpretação musical ou avaliação de ambiguidade. A recusa usa `reject_music`, sem iniciar navegador/player.

A admissão vincula a resposta ao ID que estava pendente quando o usuário falou. O controlador confere conversa, validade de 15 minutos, aba e resultado observado; só então marca `executing` no ledger antes de abrir o vídeo específico. Reutiliza a verificação de reprodução existente (ID, avanço, sem anúncio/erro). Conclusão consome a proposta; outro “sim” não reinicia a faixa. Repetições durante a execução também não cancelam a primeira confirmação.

Uma nova solicitação invalida a escolha anterior. Referência expirada, aba fechada, resultado removido/alterado ou tentativa de outra conversa não provoca busca nem seleção alternativa. Depois de uma falha incerta, repetir “sim” não repete o efeito. O ledger preserva esse estado após reiniciar; perguntas antigas podem ser recuperadas somente quando o texto da pergunta identifica um único vídeo com evidência observada. Uma pergunta genérica não cria aprovação implícita.

Testes controlados: `tests/test_music_confirmation.py`. Validação no Chrome de produção, com proposta já pendente: `scripts/validate_music_request.py --scenario confirmation --session ID --voice`. Relatório `.data/music-confirmation-live.json`; entrada de texto equivalente à fala, sem nova gravação de microfone. A configuração de fala é restaurada ao terminar.

## Recomendações da página atual

`media(check="suggestions")` aguarda até 8 segundos pelo carregamento dos cards e lê título, canal disponível, URL/ID e posição de até 50 cards renderizados da área relacionada, separando o painel da playlist. Não rola nem pesquisa para inventar opções ausentes. O snapshot inclui os cards observados para auditoria. Exige crédito/indicador musical no título ou canal (por exemplo, Artista — Faixa, clipe, audio ou VEVO); títulos isolados sem esses dados podem ser recusados por evidência insuficiente. Cards Mix/coleção, anúncios, Shorts, vídeo atual, entrevistas, reações, covers e títulos explicitamente motivacionais/edits são excluídos. Links comuns com `list=RD...&start_radio=1` são normalizados para o vídeo individual; esses parâmetros sozinhos não significam um card Mix.

`media(check="recommendation", query="pedido completo")` usa o Qwen CPU para interpretar o artista/contexto e escolher um ID fornecido. Exemplos: “Toque a primeira sugestão”, “Outra deles”, “Próxima da mesma banda”, “Coloque outra do NX Zero pelas sugestões”. A primeira sugestão não restringe banda. Evidências no título permitem selecionar música publicada por gravadora; menções negativas são filtradas. Sem artista identificável, pergunta qual banda; sem correspondência, oferece busca sem executá-la.

A análise usa lotes de 20 opções na ordem para preservar o contexto de 4096 tokens. Schema e validação restringem a escolha à primeira opção com evidência, rejeitam IDs inventados e escolhas posteriores indevidas. O snapshot é conferido antes da navegação; uma mudança permite nova leitura/análise uma vez. A confirmação existente exige vídeo escolhido diferente do anterior, sem anúncio/erro e com tempo avançando. Uma continuação simples mantém uma única operação/checkpoint, mesmo se o planejador sugerir busca adicional ou repetir a chamada.

Após reinício, recupera-se uma aba única do último vídeo confirmado ou uma única reprodução ativa do YouTube. Havendo ambiguidade, é necessário selecionar uma aba. `Selecione a aba https://www.youtube.com/watch?v=...` aceita somente endereço explícito do usuário e uma única aba já existente; não navega nem cria cópia.

Ensaios controlados: `tests/test_youtube_suggestions.py`, `tests/test_tools_architecture.py`. IA CPU com dados controlados: `scripts/validate_suggestions_model.py`. Ensaio real no controlador de produção: `scripts/validate_youtube_suggestions.py --session <conversa> --video <URL já aberta>`. `--inspect` apenas seleciona/lê. O ensaio desativa temporariamente a fala e restaura a configuração ao terminar; não mede uma nova captura de microfone.

## Correção de saudação antes do pedido

A transcrição real `Boa noite, Javis. Abra o Google, entre no YouTube, toque uma música do Guns and Rolls.` não entrava no caminho direto: a primeira cláusula ainda continha saudação e vocativo. O plano do modelo foi recusado por `media: check inválido` antes de executar ferramentas. A remoção de prefixos conversacionais agora preserva o corpo do pedido e os conteúdos de notas/buscas. A gramática JSON do modelo passou a vincular cada ação aos próprios argumentos, enums e campos obrigatórios, derivados do registro central.

Regressão: frase exata e variações com outros artistas/saudações, preservação de texto de notas, três etapas em ordem e zero inferências. Suíte atual: **94 testes Python aprovados**. Ensaio real oculto/silenciado confirmou Google → YouTube → Sweet Child O’ Mine, em 21,12 s incluindo rede, com zero tokens. Pausa, retomada, próxima/anterior e volume passaram. O ensaio também validou o novo schema no Qwen CPU real para um pedido novo, com 0 bytes de VRAM reportados. Relatório atualizado: `.data/tools-validation.json`. O termo do artista é mantido como transcrito; não há regra específica para corrigir ou executar um artista.

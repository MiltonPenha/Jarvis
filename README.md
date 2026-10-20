# JARVIS / Hermes

Assistente pessoal em português brasileiro com o HUD original, FastAPI e voz local. O modo **Local · CPU** executa comandos básicos diretamente ou interpreta pedidos com Qwen3 1.7B. Os provedores de nuvem continuam disponíveis pelo **Hermes Agent oficial da Nous Research**.

Checkpoint de 20/10/2026: [estado atual, preparação e guia de retomada](docs/RETOMADA.md). O código, testes e documentação estão preservados para a pausa no desenvolvimento; credenciais e dados pessoais permanecem locais.

Estado em 15/10/2026: ferramentas reutilizáveis com contexto de aba/player, volume nativo do Windows e comandos diretos sem tokens em qualquer provedor. [Arquitetura, comandos, extensão e validação atual](docs/TOOLS.md). O modo básico local não faz chamadas pagas nem fallback automático para Gemini. A voz Qwen aprovada e o Whisper continuam locais em CPU. Tempo por localização aproximada, navegação por elementos, aplicativos, notas e avisos persistentes estão descritos em [Comandos básicos locais](docs/LOCAL_BASICS.md), incluindo medidas de recursos e limitações.

## Iniciar

O ambiente já foi preparado neste computador. Execute `start_jarvis.bat` ou, no PowerShell, dentro desta pasta:

```powershell
.\.venv\Scripts\python.exe run_jarvis.py
```

Abra [JARVIS local](http://127.0.0.1:8000). O iniciador abre uma janela própria do Chrome/Edge; executar `start_jarvis.bat` novamente reabre a interface da instância ativa, sem duplicar o servidor. O microfone começa desligado. Fechar/recarregar uma aba preserva a execução e o histórico. Para encerrar, use **ENCERRAR**, `stop_jarvis.bat` ou Ctrl+C. Há uma única instância por porta e encerramento dos workers e tarefas.

Para reiniciar, aguarde `stop_jarvis.bat` confirmar que a porta foi liberada e execute o iniciador novamente. O atalho `PARAR_JARVIS.bat` da área de trabalho usa esse mesmo encerramento. Se uma queda deixar o worker privado da IA aberto, a próxima inicialização dele recupera apenas o processo registrado deste projeto, após validar identidade e ausência do proprietário; processos ativos ou desconhecidos são preservados.

Para preparar novamente:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1
```

O script cria `.venv` para o JARVIS e prepara o checkout oficial do Hermes pelo **PM oficial**, em runtime separado. Não instala um pacote homônimo do PyPI nem modifica o código do Hermes. A revisão verificada é `7bda2a3368024f7ae1c70cef16583e7c2c891674`. As dependências próprias testadas estão em `requirements.lock.txt`; `requirements.txt` declara faixas compatíveis. Para repetir exatamente o ambiente próprio, use `.venv/Scripts/python.exe -m pip install -r requirements.lock.txt`. O runtime Hermes usa seu próprio lock, sem misturar bibliotecas com o servidor.

## Configurar OpenAI e Gemini

1. Edite `.env` localmente e preencha `OPENAI_API_KEY` e/ou `GEMINI_API_KEY` (`GOOGLE_API_KEY` também é aceito). Não cole chaves no chat ou no HUD. Uma chave não vazia no `.env` vence uma variável herdada; campos vazios preservam o ambiente.
2. Reinicie o JARVIS. Em **CONFIGURAÇÕES**, escolha **OpenAI API** ou **Google Gemini**. A lista **Modelo** carrega automaticamente; escolha um item e salve. **Atualizar modelos** refaz a consulta. O campo mostra falhas de credencial/rede e mantém a escolha salva quando a consulta falha. Também é possível definir `JARVIS_PROVIDER` e `JARVIS_MODEL` antes da primeira configuração no painel.
3. O painel mantém as escolhas em `.data/settings.json`. Essas escolhas vencem os defaults de provedor/modelo no `.env`.
4. O fallback começa desativado. Se habilitado, exige provedor e modelo explícitos, é anunciado e só pode acontecer antes de qualquer ferramenta com efeito ser admitida. Uma falha após efeitos não reexecuta o turno em outro provedor.

O Hermes resolve `openai-api` para a API Responses da OpenAI e `gemini` para seu adaptador nativo Gemini. O nome interno `codex_responses` do Hermes para a primeira rota **não exige assinatura Codex/ChatGPT**: a credencial é a chave da API e o destino é `api.openai.com`. Identificadores e capacidades dependem do catálogo e do acesso da conta. O catálogo é filtrado, mas aparecer na lista não garante acesso à geração ou a todas as ferramentas.

Os provedores de nuvem não exigem Ollama. No modo Local · CPU, o JARVIS usa o executável Ollama instalado em um serviço privado, na porta 11439, com armazenamento próprio e GPU desabilitada. O modelo Hermes 3 não está em execução. Consulte [a revisão de limpeza](docs/CLEANUP.md) como registro da etapa anterior.

## Comandos básicos locais

O modelo já está preparado neste computador. Em Configurações, use **Local · CPU → qwen3:1.7b**. Para preparar o mesmo modelo em outra instalação com Ollama: `.venv/Scripts/python.exe scripts/setup_local_model.py`. A preparação baixa aproximadamente 1,4 GB; o uso posterior do modelo não exige internet nem chave.

```text
Qual o tempo agora?
Tempo em Curitiba
Abra a calculadora
Abra o Google
Pesquise no Google receitas de café
Clique no resultado 1
Abra o Google, entre no YouTube e toque uma música do Guns and Roses
Pause a música
Continue
Aumente um pouco o som
Diminua para 30%
Passe para a próxima
Toque a primeira sugestão
Toque a primeira sugestão da mesma banda
Outra deles
Liste as sugestões do YouTube
Qual música está tocando?
Coloque o volume do sistema em 40%
Leia a página
Role para baixo
Anote que preciso comprar leite
Me lembre de beber água em 10 minutos
Crie um alarme amanhã às 8:30
Meus lembretes
Pare o alarme
```

O navegador usa o Chrome habitual por conexão CDP autorizada e confirma o perfil selecionado. Reutiliza uma aba única do YouTube ou abre outra no mesmo perfil, verifica o login no próprio site e preserva as demais abas. Configure em **Configurações → Navegador**; o perfil separado é uma alternativa explícita. Veja [conexão e validação do Chrome](docs/CHROME.md). Os avisos precisam do JARVIS aberto e do PC acordado; persistem após reiniciar. O tempo usa internet e localização aproximada pelo IP. O Google pode pedir verificação humana. Consulte [os detalhes e a validação](docs/LOCAL_BASICS.md).

O fluxo de voz mantém original, texto normalizado e intenção separados. O microfone indica ESCUTANDO depois de abrir a captura; pedidos durante uma tarefa podem aguardar ou interromper conforme Configurações. Parâmetros, diagnóstico e ensaio com voz humana: [VOICE_CHAIN.md](docs/VOICE_CHAIN.md).

Correções explícitas de artista têm prioridade sobre a consulta anterior. Quando um nome transcrito não corresponde aos resultados, a IA local pode conferir candidatos observados no YouTube, na CPU e sem API paga; dúvidas pedem confirmação. A geração da voz e sua reprodução têm prazos separados para a preparação do áudio não consumir o tempo de fala.

## Usar

- Texto: envie um pedido no terminal. Acompanhe **processando**, **executando ferramenta**, **concluído**, **falhou** ou **cancelado**. **INTERROMPER** para a tarefa e o áudio; desligar o microfone/parar voz tem botão próprio.
- Voz: em **CONFIGURAÇÕES → Microfone**, escolha a entrada desejada e salve. A escolha é do JARVIS e não altera o padrão do Windows. Clique no microfone para um turno. Na escuta contínua, diga “Jarvis” no pedido; somente um capturador opera, e não há gravação enquanto o assistente fala. A captura encerra após silêncio ou limite de duração. A transcrição continua usando o mesmo serviço e sessão do texto.
- Sem chave válida: atalhos locais de status, navegador, música, captura e vault continuam disponíveis sem modelo e sem tokens. Música usa a janela controlada do YouTube e só anuncia reprodução depois de observar o avanço do player; anúncios, carregamento e verificação humana são informados quando impedem a confirmação.
- **Nova conversa** cria outra sessão. **Histórico** restaura pedidos e resultados do ledger no modo básico local; nos provedores de nuvem, também mostra os resultados do ledger para preservar comandos diretos; sessões antigas sem tarefas locais continuam disponíveis pelo Hermes. Nas tarefas do painel, **Abrir conversa** recupera uma sessão anterior, inclusive após reiniciar.
- Use a área de tarefas para conferir resultados, erros e checkpoints. Retomada reutiliza ações já verificadas; um efeito incerto/falho exige inspeção e uma nova instrução específica. Não existe promessa de execução “exatamente uma vez” contra sistemas externos após uma queda: o sistema prefere bloquear uma repetição incerta.

Exemplos para os provedores de nuvem pelo Hermes (fora do modo básico local):

```text
Guarde minha preferência: respostas em português, com um resumo primeiro.
Procure no vault as decisões sobre meu projeto e cite as notas e linhas.
Localize os testes no diretório autorizado, leia o erro, faça a correção e execute unittest.
Compare os trechos relevantes de dois documentos na pasta workspace e cite as fontes.
```

## Arquitetura e fontes de verdade

```text
HUD e microfone → FastAPI → fila e ledger de tarefas → worker Hermes AIAgent
                                                     ↓ modelo/provedor
                       ferramentas registradas no Hermes → executor do host
```

No modo local, a mesma fila usa `LocalRuntime`: atalhos ou plano JSON do Qwen → ferramentas validadas → checkpoints e resposta baseada no resultado. Não passa pelo ciclo Hermes de contexto amplo; o modelo pequeno recebe o pedido, o catálogo e o contexto operacional compacto. Planos admitidos ficam nos checkpoints existentes; não há segundo agente autônomo. Histórico e memória do Hermes são preservados.

| Informação | Responsável |
|---|---|
| Mensagens, chamadas e resultados de conversa | `SessionDB` oficial do Hermes em `.data/hermes/state.db` |
| Perfil e memória essencial | `MemoryStore` oficial: `.data/hermes/memories/USER.md` e `MEMORY.md` |
| Conhecimento e projetos | Markdown no vault Obsidian; busca FTS5 incremental descartável em `.data/vault-index.sqlite3` |
| Pedidos, estados, efeitos e checkpoints | `.data/tasks.sqlite3`; snapshots de pedido/resultado existem para auditoria e retomada, não como outro agente/histórico de mensagens |
| Preferências de execução | `.env` e `.data/settings.json`; o arquivo de configuração Hermes é gerado pelo JARVIS |
| Correções de memória e revisões | `.data/memory-events.json` (últimos 200 eventos) e `.data/revisions/` |

O Hermes faz as chamadas ao modelo, administra o ciclo de ferramentas e mantém a associação de IDs. `registry.register` registra a extensão `jarvis`. O handler roda no worker; operações com bibliotecas de documentos, áudio, web e Windows são encaminhadas ao host por JSONL. O Hermes continua coordenando a chamada e recebe seu resultado, sem instalar dependências próprias do JARVIS no ambiente do Hermes. O cancelamento usa `AIAgent.interrupt`; um worker que não encerra é finalizado com sua árvore de processos.

O histórico carregado para o modelo é cortado em turnos completos até o orçamento de caracteres, preservando chamadas e resultados. O histórico completo permanece pesquisável no Hermes. Os limites nativos de restauração também se aplicam; sessões muito grandes podem exigir uma nova conversa. Não há resumo, embedding ou reflexão externa automática. Não há provedor auxiliar oculto.

## Memória e aprendizado por uso

**Consultar memória**, **Corrigir**, **Excluir** e **Lembrar e verificar** operam no `MemoryStore` do Hermes e reabrem o armazenamento para confirmar a gravação. Os limites são 1.375 caracteres de perfil e 2.200 de notas essenciais. Afirmações têm origem (`user_statement`, `document`, `observed`); inferências são recusadas como fatos essenciais. As correções geram registro local. Exclusão da memória essencial não apaga os registros de auditoria, backups ou conversas antigas.

O vault original foi preservado. `User/Perfil.md` e `User/Preferencias.md` legados são fontes consultáveis; não foram promovidos automaticamente a fatos no novo perfil. Notas são buscadas antes da leitura, retornam caminho/linha/data, e atualizações exigem hash da versão lida. A gravação usa substituição atômica, lock entre processos, backup e releitura. Notas escritas pelo JARVIS guardam origem e data em comentário Markdown. O painel bloqueia a edição de uma nota exibida apenas parcialmente.

Procedimentos podem ser gravados no diretório de skills do Hermes por `skill_save` depois de uma tarefa concluída com **unittest realmente executado e aprovado**, com pelo menos um teste. Compilação isolada não torna um procedimento confiável. `skill_list`/`skill_read` recuperam instruções sob demanda. Isso é memória e reutilização de procedimentos, **não treinamento de pesos**. A geração automática de skills por reflexão está desativada. Skills não ampliam permissões.

## Ferramentas e permissões

O diretório padrão é `workspace/`. Autorize outros diretórios explicitamente em `JARVIS_WORKSPACE_ROOTS`, separados por `;`, e reinicie. A interface não pode ampliar essa lista ou alterar credenciais. Ferramentas incluem busca/leitura/edição de texto e código, leitura de PDF com texto e DOCX, vault, busca web DDGS com fontes, memória, histórico, skills, aplicativos conhecidos, mídia, capturas e macros existentes em `commands.json`.

Arquivos ocultos, `.env`, credenciais e chaves privadas são bloqueados nas ferramentas de arquivo. Caminhos são resolvidos antes do acesso, inclusive travessias e links. Edições existentes exigem hash e geram diferenças/revisões. PDF escaneado sem texto pede OCR e não finge ter sido lido. Tamanho por arquivo: 2 MB; resultados do modelo são limitados. Busca web usa DDGS; não há resumo por outro LLM.

Comandos são limitados a `unittest` e compilação Python, com timeout de 30 s, saída limitada, diretório autorizado e ambiente sem chaves. **Esse executor não é um sandbox do sistema operacional:** testes são código do projeto e rodam com os direitos do usuário. Use apenas projetos confiáveis nos diretórios autorizados. Shell arbitrário, compras, publicação, envio de mensagens e ações destrutivas não estão expostos. Acrescentá-los exige uma política de confirmação específica; o JARVIS atual os recusa.

O servidor aceita somente localhost, verifica Host/Origin e usa cookie HttpOnly/SameSite. Não há CORS aberto. Dados de documentos, notas e páginas não concedem permissões. Segredos são filtrados antes de resultados, memórias e logs próprios. O app não é um serviço para publicar na rede.

## Voz e custo

- **Edge TTS**: implementação preservada, agora com voz `pt-BR-AntonioNeural`, ritmo calmo e texto limpo. Envia o texto à Microsoft via projeto `edge-tts`; depende desse serviço online e não oferece o mesmo contrato de uma API comercial. Código do `edge-tts` usa predominantemente LGPLv3; a licença do cliente não é licença irrestrita do serviço.
- **Qwen local (seleção atual)**: referência JARVIS recriada com Qwen 0.6B ONNX INT4. Usa oito threads de CPU e cerca de 1,6 GiB de RAM do sistema, sem GPU, API de voz ou cobrança por tokens. O modelo é reutilizado e liberado após três minutos ocioso. A síntese tem espera relevante: aproximadamente 7,5 s para uma frase de 1,7 s; uma frase maior levou 26,8 s. A semelhança deve ser avaliada pela amostra. Prepare com `.venv/Scripts/python.exe scripts/setup_qwen_voice.py` e selecione Qwen local no painel; esse setup preserva as preferências existentes.
- **Fish Audio (voz escolhida)**: “Jarvis (UCM) - Português Brasileiro”, identificador fixo `a5b93aeddcc948c19ea04f0afe9d178c`. Exige `FISH_API_KEY` no `.env` e reinício. O texto da resposta vai à Fish Audio para síntese; não recebe o microfone. O motor explícito é `s2.1-pro-free`, sujeito ao acesso/limites da conta. Sem chave ou em erro, a mensagem fica visível e não há troca automática de voz/motor. [Criar chave](https://fish.audio/app/api-keys).
- **Piper/Faber local (alternativa manual)**: voz neural pt-BR, com ritmo mais pausado e síntese em CPU. Modelo e fonemizador são preparados na inicialização quando selecionado; depois não há download ou serviço externo na síntese. Os pesos têm cerca de 63 MB. O perfil de fala usa `JARVIS_PIPER_LENGTH_SCALE=1.18`.
- **Windows local (opcional)**: SAPI, voz brasileira instalada (Maria neste computador). Continua disponível por escolha explícita, sem fallback automático para ela.
- **OpenAI áudio**: API oficial; exige `OPENAI_TTS_MODEL`/`OPENAI_STT_MODEL`, tem custo separado do raciocínio e usa `OPENAI_API_KEY`. Modelos não são presumidos.
- **Transcrição local (padrão)**: Whisper `base` multilíngue, CPU/int8 e quatro threads. O modelo foi preparado em `.data/models/whisper-base`; a captura não faz downloads e usa somente arquivos locais. A instância é carregada na inicialização sem ligar o microfone e reutilizada nos próximos pedidos. Google Web Speech/OpenAI continuam como opções explícitas online.

O raciocínio continua no Gemini pela API e a transcrição usa Whisper local. A voz atual é recriada localmente a partir da amostra do link com Qwen em CPU. Fish Audio permanece uma opção online para a referência exata do catálogo, ainda sem geração real por falta de chave. `scripts/setup_voice.ps1` prepara e seleciona a alternativa Piper/Whisper, preservando IA, credenciais e microfone; executá-lo troca a voz ativa para Piper. Consulte [a configuração de áudio](docs/AUDIO_LOCAL.md).

Após o usuário esclarecer que a restrição era VRAM, a voz Qwen foi integrada e selecionada com oito threads de CPU. Medições reais de CPU, RAM e tempo com os demais programas abertos estão em [VOICE_RESOURCES.md](docs/VOICE_RESOURCES.md).

A fala remove Markdown, código, URLs e logs, limita aproximadamente 700 caracteres e preserva o texto completo na tela. A interrupção impede que uma síntese cancelada comece a tocar. A captura tenta 16 kHz e usa a frequência nativa quando necessário, preservando essa frequência na transcrição. O G522 foi aberto fisicamente a 48 kHz com sinal recebido; o reconhecimento da voz do usuário e a avaliação perceptiva ainda precisam de teste manual. Há evidência técnica de síntese Edge e transcrição Google em [VALIDATION.md](docs/VALIDATION.md).

Limites iniciais: 6 etapas, 1.500 tokens de saída por chamada, 24.000 caracteres de histórico, 120 s totais por tarefa, 30 pedidos/dia e 100.000 tokens/dia na admissão (contabilização UTC). Uma tarefa em curso pode ultrapassar o limite diário; ele não equivale a teto financeiro na conta do provedor. Hermes recebe duas tentativas de API no nível do agente, sem recuperação automática ilimitada; os transportes podem ter reconexões próprias, limitadas pelo prazo global.

O painel mostra uso reportado, chamadas, cache quando disponível, tempo da primeira resposta e duração. A contagem exata de retentativas não é exposta de forma confiável e fica desconhecida. Estimativas só aparecem com preços e data configurados; o cálculo simples não desconta cache e fica indisponível para o custo conjunto de fallback. Voz e serviços fora do modelo principal não estão incluídos nessa estimativa. Não houve geração paga bem-sucedida nesta implementação.

## Verificação e manutenção

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts/doctor.py --providers
.\.venv\Scripts\python.exe scripts/validate_voice.py
.\.venv\Scripts\python.exe -m pip check
.\.runtime\tools\node-26.7.0-win32-x64\node.exe --test tests/test_model_selectors.cjs
```

`doctor --providers` consulta os catálogos, sem gerar texto. `validate_voice` sintetiza uma frase artificial e a transcreve, sem reproduzir áudio ou gravar o microfone. Os testes usam vault e workspace temporários, sem alterar seu vault real. O teste de ciclo Hermes usa um servidor de modelo controlado localmente e está explicitamente separado de validação com a nuvem.

A [bateria musical reutilizável](docs/MUSIC_EVALUATION.md) separa desenvolvimento e reserva por obra/artista, mede seis etapas e compara relatórios antes/depois com hashes do corpus/modelo. `scripts/evaluate_music.py` oferece avaliação offline, gravações locais com referências confirmadas e uma integração menor no Chrome real. Testes não treinam o modelo; áudio humano, resultados controlados e reprodução real têm identificação separada nos relatórios.

O [relatório de feedback e voz local](docs/FEEDBACK_VOICE.md) explica os novos estados do HUD, os limites de fala, a comparação Qwen/Piper em CPU e as medições reais. Em Configurações, **Ouvir e comparar** permite testar as mesmas frases sem trocar a voz salva; a saída de voz aceita somente sintetizadores locais.

Veja [auditoria e decisões](docs/AUDIT.md), [testes e limites conhecidos](docs/VALIDATION.md) e [próximos passos](docs/PROGRESS.md). A documentação oficial consultada está vinculada nesses arquivos.

# JARVIS / Hermes

Assistente pessoal em português brasileiro com o HUD original, FastAPI, voz e **Hermes Agent oficial da Nous Research** como único ciclo de modelo e ferramentas. O antigo agente “inspirado no Hermes”, o histórico em RAM e o fallback Pollinations foram retirados.

Estado da implementação em 15/10/2026: execução local, memória, ferramentas, fila e voz verificadas. O usuário selecionou `gemini-3.6-flash` e recebeu uma resposta real. A voz padrão agora é neural local (Piper/Faber), com transcrição Whisper local. Consulte [a validação e as pendências](docs/VALIDATION.md).

## Iniciar

O ambiente já foi preparado neste computador. Execute `start_jarvis.bat` ou, no PowerShell, dentro desta pasta:

```powershell
.\.venv\Scripts\python.exe run_jarvis.py
```

Abra [JARVIS local](http://127.0.0.1:8000). O iniciador abre uma janela própria do Chrome/Edge; executar `start_jarvis.bat` novamente reabre a interface da instância ativa, sem duplicar o servidor. O microfone começa desligado. Fechar/recarregar uma aba preserva a execução e o histórico. Para encerrar, use **ENCERRAR**, `stop_jarvis.bat` ou Ctrl+C. Há uma única instância por porta e encerramento dos workers e tarefas.

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

O funcionamento não exige credencial da Anthropic nem Ollama. O Hermes Agent coordena o modelo escolhido no provedor; o modelo local Hermes 3 não está em execução. O painel atual expõe apenas OpenAI e Gemini. Perfis automáticos por qualidade/preço e visão não foram apresentados como capacidades concluídas. Consulte [a revisão de limpeza](docs/CLEANUP.md) para os itens removidos e a configuração vigente.

## Usar

- Texto: envie um pedido no terminal. Acompanhe **processando**, **executando ferramenta**, **concluído**, **falhou** ou **cancelado**. **INTERROMPER** para a tarefa e o áudio; desligar o microfone/parar voz tem botão próprio.
- Voz: em **CONFIGURAÇÕES → Microfone**, escolha a entrada desejada e salve. A escolha é do JARVIS e não altera o padrão do Windows. Clique no microfone para um turno. Na escuta contínua, diga “Jarvis” no pedido; somente um capturador opera, e não há gravação enquanto o assistente fala. A captura encerra após silêncio ou limite de duração. A transcrição continua usando o mesmo serviço e sessão do texto.
- Sem chave válida: atalhos locais de status, navegador, música, captura e vault continuam disponíveis sem modelo e sem tokens. Abrir uma busca musical não é comprovação de reprodução.
- **Nova conversa** cria outra sessão. **Histórico** restaura mensagens do Hermes. Nas tarefas do painel, **Abrir conversa** recupera uma sessão anterior, inclusive após reiniciar.
- Use a área de tarefas para conferir resultados, erros e checkpoints. Retomada reutiliza ações já verificadas; um efeito incerto/falho exige inspeção e uma nova instrução específica. Não existe promessa de execução “exatamente uma vez” contra sistemas externos após uma queda: o sistema prefere bloquear uma repetição incerta.

Exemplos após configurar um modelo válido:

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
- **Fish Audio (voz escolhida)**: “Jarvis (UCM) - Português Brasileiro”, identificador fixo `a5b93aeddcc948c19ea04f0afe9d178c`. Exige `FISH_API_KEY` no `.env` e reinício. O texto da resposta vai à Fish Audio para síntese; não recebe o microfone. O motor explícito é `s2.1-pro-free`, sujeito ao acesso/limites da conta. Sem chave ou em erro, a mensagem fica visível e não há troca automática de voz/motor. [Criar chave](https://fish.audio/app/api-keys).
- **Piper/Faber local (alternativa manual)**: voz neural pt-BR, com ritmo mais pausado e síntese em CPU. Modelo e fonemizador são preparados na inicialização quando selecionado; depois não há download ou serviço externo na síntese. Os pesos têm cerca de 63 MB. O perfil de fala usa `JARVIS_PIPER_LENGTH_SCALE=1.18`.
- **Windows local (opcional)**: SAPI, voz brasileira instalada (Maria neste computador). Continua disponível por escolha explícita, sem fallback automático para ela.
- **OpenAI áudio**: API oficial; exige `OPENAI_TTS_MODEL`/`OPENAI_STT_MODEL`, tem custo separado do raciocínio e usa `OPENAI_API_KEY`. Modelos não são presumidos.
- **Transcrição local (padrão)**: Whisper `base` multilíngue, CPU/int8 e quatro threads. O modelo foi preparado em `.data/models/whisper-base`; a captura não faz downloads e usa somente arquivos locais. A instância é carregada na inicialização sem ligar o microfone e reutilizada nos próximos pedidos. Google Web Speech/OpenAI continuam como opções explícitas online.

O raciocínio continua no Gemini pela API e a transcrição usa Whisper local. Por escolha do usuário, a voz específica do link usa a API Fish Audio. A integração está preparada, mas a geração real aguarda a chave do usuário. `scripts/setup_voice.ps1` prepara e seleciona a alternativa local Piper/Whisper, preservando IA, credenciais e microfone; executá-lo troca a seleção da Fish Audio para Piper. Consulte [a configuração de áudio](docs/AUDIO_LOCAL.md).

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

Veja [auditoria e decisões](docs/AUDIT.md), [testes e limites conhecidos](docs/VALIDATION.md) e [próximos passos](docs/PROGRESS.md). A documentação oficial consultada está vinculada nesses arquivos.

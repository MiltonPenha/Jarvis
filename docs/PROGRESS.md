# Progresso e continuidade

Entregue em 15/10/2026: stack preservada, runtime Hermes oficial, extensão real de ferramentas, fila única, sessões/memória nativas, vault indexado, gravação verificada, ledger/checkpoints, cancelamento, áudio pt-BR, painel operacional e ambientes reproduzíveis. Veja README, auditoria e validação para os limites exatos de cada capacidade.

## Próximos passos priorizados

1. **Escolher um modelo e validar a primeira conversa real.** A chave Gemini atual consultou o catálogo com sucesso; o painel carrega os modelos automaticamente e mostrou 19 opções de conversa. Provedor local salvo: Gemini; modelo continua aguardando escolha. Não enviar segredos ao chat. Começar com pedidos curtos e ferramentas sem efeitos externos. A falha de autenticação anterior do Gemini é evidência histórica, não o estado atual.
2. **Validar os dois provedores reais.** Conversação pt-BR, uma ferramenta de arquivo de teste, leitura de resultado, segunda interação na mesma sessão e troca de provedor preservando memória/IDs. Medir tokens, latência e custos com tabela de preços datada. Não escolher um modelo “definitivo” antes disso.
3. **Validar microfone e qualidade perceptiva.** Seguir o roteiro em VALIDATION.md. A síntese/transcrição artificial já funciona; dispositivo, ruído e naturalidade exigem escuta/captura reais.
4. **Ensaiar tarefas prolongadas.** Correção de projeto autorizado, falha transitória, interrupção, reabertura do processo e retomada. Medir RAM, número de processos, crescimento do banco e tamanho de contexto por várias tarefas. Rever retenção de revisões e logs com dados de uso.
5. **Ampliar documentos e verificações.** Cobrir PDF com texto, documentos extensos e imagens/OCR; acrescentar ferramentas de teste de outras stacks por perfis explícitos de comando. O executor atual só oferece unittest/compilação Python, sem shell livre.
6. **Melhorar configuração e áudio.** Paginação do histórico, editor de notas extensas, presets de qualidade/velocidade/economia, métricas/preços por modelo e provedor de voz; avaliar streaming por frases, VAD neural e transcrição local. A RTX 4060 Ti/8 GB não foi ocupada por modelos de raciocínio nesta etapa.
7. **Integrações de maior impacto.** Publicação, envio de mensagens, shell arbitrário e ações destrutivas continuam sem ferramentas expostas. Ao acrescentá-las, implementar aprovação específica, recuperação e chaves de idempotência próprias da integração; uma skill ou documento nunca pode autorizar esses acessos.

## Estado seguro para retomar

- `.env` foi normalizado conforme `.env.example`, com as credenciais utilizadas preservadas. A versão anterior está no backup externo indicado em CLEANUP.md.
- Os dados do usuário no vault original não foram usados como alvo de gravações de teste.
- Dados de produção: `.data/` e vault configurado. Testes: diretórios temporários dedicados.
- Checkout do Hermes está isolado em `.runtime/hermes-agent`, sem alterações internas.
- O cache de seleção de ambiente em `.runtime/runtime.json` contém somente caminhos, não o ambiente completo ou credenciais. Refaça `python -m core.hermes_runtime` após preparar/mudar o runtime.
- O arquivo `.data/hermes/config.yaml` é gerado pelo JARVIS. Ajustes de provedor/modelo ficam no painel ou defaults de `.env`; limites ficam no backend. Não edite o arquivo gerado como fonte de configuração.
- Evite empilhar uma instância manual sobre a inicialização automática. O runner recusa porta já ocupada; o registro de autostart só muda por ação explícita.

## Pendências deliberadas

Sem confirmação automática para tarefas perigosas porque essas ferramentas ainda não estão expostas; sem treinamento de pesos; sem embeddings ou reflexão externa automática; sem promessa de navegação visual/computer-use geral; sem voz clonada; sem fallback invisível; sem ensaio de produção apresentado como aprovado. Perfil legado não foi convertido cegamente em fatos nativos.

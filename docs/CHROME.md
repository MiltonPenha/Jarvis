# Chrome habitual e YouTube — 17/10/2026

## Causas observadas

O processo antigo usava `.data/browser-profile`; o Chrome habitual usava `Default`. No pedido registrado com “entra no YouTube”, o plano abriu os dois sites e tentou clicar em um título de vídeo inventado na página inicial, sem pesquisa anterior. A ferramenta recusou o alvo e devolveu uma mensagem pedindo um número de elemento. Outra execução sequer incluiu a ferramenta de música.

Foram corrigidas a composição de verbos, a preparação dos planos e a conexão. `play_music(query)` realiza pesquisa, seleção e verificação do player; o plano não precisa inventar um link. Intenções de continuação como “outra do mesmo artista” permanecem uma única operação de mídia.

## Conexão suportada

O mesmo `BrowserControl` usa `chromium.connect_over_cdp(..., no_defaults=True)` e o contexto existente. O padrão é o canal `chrome`, suportado pelo Playwright 1.64 instalado. O Chrome instalado nesta validação é o 155. O endpoint HTTP local configurado também é aceito; quando a porta coincide com `DevToolsActivePort`, o controlador usa o caminho WebSocket publicado pelo próprio Chrome. Isso evita depender de `/json/version`, que retornou 404 nesta instância, e mantém a configuração estável após reiniciar o navegador.

O perfil é conferido por `chrome://version` em uma aba diagnóstica que é fechada em seguida. Uma aba única do YouTube é reutilizada; se houver várias, abre uma nova para evitar escolher uma sessão de mídia por engano. Somente abas admitidas pelo controlador entram nas observações/controles. Não são copiadas credenciais, cookies ou dados de sessão. Não se relança o diretório principal com flags de depuração. Desconectar/encerrar o JARVIS para de controlar e preserva as janelas pessoais.

Configuração persistida em `.data/browser-settings.json`, separada das preferências de voz/IA. **Configurações → Navegador** oferece perfil, autorização e conexão. Se o Chrome estiver fechado ou a autorização ausente, **Autorizar no Chrome** abre normalmente o perfil selecionado na página apropriada; a aprovação nativa deve ser concedida nele. Não há fallback silencioso para perfil anônimo. O modo separado continua disponível somente por escolha explícita.

Referências oficiais consultadas: [Playwright MCP](https://github.com/microsoft/playwright-mcp), [conexão nativa e extensão](https://github.com/microsoft/playwright.dev/blob/main/mcp/configuration/browser-extension.mdx), [API Python CDP](https://playwright.dev/python/docs/api/class-browsertype#browser-type-connect-over-cdp) e [restrição de flags no perfil principal desde Chrome 136](https://developer.chrome.com/blog/remote-debugging-port).

## Pesquisa e continuidade

A autorização nativa é por nova sessão de depuração, não por ferramenta/comando. Reiniciar o backend ou o Chrome, desconectar explicitamente ou perder a conexão pode exigir outra aprovação. Recarregar o HUD mantendo o backend ativo não cria outra conexão. O controlador mantém a sessão entre comandos, inclusive após fechar uma aba controlada; salvar configurações idênticas não desconecta. O script de validação usa somente o controlador de produção, sem criar outro cliente CDP para ler preferências do HUD. O prazo de conexão é 30 s para permitir responder ao aviso. Comandos comuns têm teto de 60 s quando precisam conectar, ou 45 s com conexão já estabelecida. Música/controles de mídia têm teto de 90 s para busca, possível conferência curta do artista na CPU e confirmação do player; o orçamento total da tarefa e o cancelamento continuam valendo.

O aviso de controle que permanece no topo durante a sessão é diferente do diálogo para permitir uma nova conexão. Referência: [descrição oficial do Chrome sobre autorização a cada nova sessão](https://developer.chrome.com/blog/chrome-devtools-mcp-debug-your-browser-session).

O login é observado no próprio YouTube: booleano de sessão publicado pelo site ou controle de avatar visível, sem ler identificadores da conta, cookies ou tokens. Isso evita falso negativo em layouts sem o botão de avatar antigo. Chrome sincronizado não basta. A busca usa URL codificada no mesmo perfil. Resultados são observados, pontuados por consulta/título/canal e filtrados para evitar Shorts e conteúdo claramente desconectado. Não há banda ou vídeo fixado.

Só há sucesso quando o identificador corresponde ao vídeo selecionado, o tempo avança, o player não está pausado, há dados de mídia e não existe anúncio/erro. Mudo e volume são informados; não se afirma que o áudio físico foi ouvido. Anúncio, consentimento, verificação humana, falta de login, indisponibilidade e bloqueio de reprodução retornam estados distintos. Falta de confirmação deixa a tarefa como falha, sem anunciar conclusão.

Pausa, retomada, volume e próxima usam a mesma aba/identidade de mídia. Volume padrão é o player; Windows só muda com pedido explícito. Referências de elementos carregam aba e versão, têm histórico volátil e são remapeadas semanticamente após mudanças do DOM; não são transferidas a outra página/aba. Elementos ocultos e duplicatas de um mesmo destino são tratados internamente. Recuperação ocorre antes do efeito e tem duas tentativas; navegação/troca/clique incertos não são repetidos cegamente.

Após reiniciar, o controlador pode recuperar o último vídeo confirmado da conversa ou uma única reprodução ativa do YouTube; múltiplas opções exigem seleção. Selecione pelo ID observado ou pela URL explícita de um vídeo já aberto. Seleção por URL só aceita uma correspondência existente, preserva a aba e não navega. A consulta de sugestões pode atualizar a identidade após autoplay sem executar controle. Próxima usa a playlist/fila quando aplicável ou as recomendações; pedidos explícitos de sugestões e mesma banda consultam a lista real com IA CPU. Veja os critérios e limites em [TOOLS.md](TOOLS.md#recomendações-da-página-atual).

Progresso chega imediatamente ao painel pelo executor comum e pela ponte do Hermes. Os logs em `.data/logs/browser-events.jsonl` incluem etapa, ação, aba, caminho da URL sem consulta, tempo, resultado e erro, com rotação. Voz, microfone, modelos e memória existentes permanecem configurados como antes.

## Validação

Execute com Chrome autorizado e JARVIS já aberto:

```powershell
.venv/Scripts/python.exe scripts/validate_chrome_session.py
.venv/Scripts/python.exe -m unittest discover -s tests -v
node --test tests/test_model_selectors.cjs
```

O ensaio real usa a API da aplicação; pode receber `--session ID_DA_CONVERSA` para atuar na mesma conversa do HUD. Pesquisa artista e título, troca de artista, pausa, retomada, volume e próxima; verifica efeitos únicos e a mesma aba. Restaura voz e volume e deixa a última música tocando. Relatório: `.data/chrome-session-validation.json`. A saída deve indicar `passed: true`; um relatório de execução anterior não substitui testar o estado atual.

Chrome aberto e YouTube autenticado foram testados nesta máquina. Falta de login, referências antigas, campos ocultos, duplicatas, aba fechada/alterada e deduplicação são cobertos por testes. Fechar todas as janelas pessoais para ensaiar Chrome fechado e provocar CAPTCHA/anúncio/restrição reais não foi feito; esses estados mantêm tratamento e exigem verificação quando ocorrerem. Nenhuma geração paga foi necessária para o ensaio.

# Comandos básicos locais — 15/10/2026

O provedor `local-cpu` usa `qwen3:1.7b`, quantização Q4_K_M, pelo Ollama existente. São seis threads, contexto de 4096 tokens, geração limitada a 600 tokens, sem raciocínio longo. A primeira opção avaliada, Qwen3.5 2B, exigia atualizar o Ollama; foi substituída pelo modelo menor compatível, sem atualizar o programa global.

## Recursos medidos neste PC

Intel i5-12600KF, 10 núcleos/16 threads, 32 GB de RAM, outros processos abertos. A validação real usa o mesmo prompt/catálogo de aplicativos da aplicação.

- Pico de RAM da árvore privada Ollama: **2070,4 MiB**, aproximadamente 2,02 GiB.
- Pico amostrado de CPU: **38,5% da capacidade total**; seis threads de inferência.
- VRAM reportada por `/api/ps`: **0 bytes** em todas as chamadas. Descoberta de GPU também desabilitada; uma colocação inesperada em VRAM provoca descarregamento e bloqueio.
- Dez casos curtos de interpretação, com parâmetros e conteúdo conferidos: dez aprovados. Isso é uma amostra funcional, não garantia de acerto para qualquer frase.
- Inferências com modelo/prompt aquecidos: aproximadamente **2,0–3,5 segundos**. Primeira chamada: cerca de **19 segundos**, sem contar transcrição, rede ou voz.
- Esses números são do modelo de texto; a voz Qwen e o Whisper consomem RAM adicional. A voz aprovada foi preservada. Confirmações faladas são curtas; detalhes permanecem no HUD.

Relatório local: `.data/local-model-validation.json`. Repetição: `.venv/Scripts/python.exe scripts/validate_local_model.py`. O ensaio só gera planos, não abre aplicativos nem cria notas/avisos. Comandos diretos conhecidos dispensam inferência. O modelo descarrega após 120 segundos sem chamadas; o processo privado encerra com o JARVIS. Abaixo de 2,5 GiB de RAM disponível, uma nova inferência é recusada.

## Funcionamento

- **Tempo:** Open-Meteo, sem chave. A cidade atual vem de IPWHOIS, com cache de 30 minutos e indicação de aproximação; VPN ou operadora podem mudar o resultado. `Tempo em Curitiba` usa geocodificação explícita. Consulta real confirmou tempo para a cidade aproximada de Sorocaba. Fontes: [Open-Meteo](https://open-meteo.com/en/docs), [IPWHOIS](https://ipwhois.io/documentation).
- **Navegador:** Chrome habitual, via Playwright CDP autorizado, com perfil conferido no próprio Chrome e login do YouTube observado separadamente. Configuração e autorização em **Configurações → Navegador**; `.data/browser-profile` fica apenas como alternativa explicitamente selecionada. Pesquisa Google, URLs públicas, links por texto/referência observada, campos de texto, pesquisa, leitura, voltar e rolagem. Referências incluem aba/observação, com remapeamento semântico limitado; cliques/efeitos incertos não são repetidos automaticamente. O processamento do navegador continua entre comandos para manter páginas e mídia funcionando. Desconectar preserva as janelas pessoais. O modelo não fornece JavaScript ou seletores livres. Senhas, anexos, compras e envios genéricos de formulários ficam manuais. Veja [CHROME.md](CHROME.md).
- **YouTube e música:** `Toque uma música do Guns and Roses` ou a sequência `Abra o Google, entre no YouTube e toque uma música do Guns and Roses`. A gramática genérica de sequências combina cada ordem reconhecida, sem regra por artista ou sequência. Ela abre Google, abre YouTube e chama a busca/reprodução: três etapas distintas. Consulte [Ferramentas reutilizáveis](TOOLS.md) para controles, contexto e validação atual. A faixa é escolhida entre resultados observados, com preferência por canal correspondente ao artista e sem priorizar covers/compilações. A confirmação exige avanço real do player da faixa, sem anúncio ativo. Login, cookies, vídeo indisponível ou carregamento pendente são informados. Não baixa arquivos de música. Interromper durante a execução bloqueia novas etapas; não reabre uma janela depois do cancelamento.
- **Google:** o ensaio real recebeu verificação humana. O JARVIS mostra essa condição; a busca não é declarada concluída. Resolva na janela própria e peça `Leia a página`. Não há quebra de CAPTCHA ou troca silenciosa de buscador.
- **Aplicativos:** catálogo conhecido mais registros App Paths e atalhos instalados do menu Iniciar. São abertos pelo nome; não há comando shell livre nem argumentos produzidos pelo modelo. Algumas aplicações sem registro/atalho podem precisar de cadastro manual.
- **Projetos:** aliases das macros de pastas existentes e subpastas dos diretórios autorizados. Uma pasta escolhida é aberta no Explorer. Não amplia as permissões de edição de arquivos.
- **Anotações:** Markdown em `Notes/` no vault Obsidian já configurado. O corpo é copiado das palavras do usuário. Nomes únicos e checkpoints impedem duplicação em uma repetição do mesmo ID.
- **Lembretes e alarmes:** `.data/reminders.sqlite3`; instante UTC e horário local do Windows. Expressões como `em 10 minutos`, `amanhã às 8:30` e `às 14:30`. Aviso sonoro do Windows e faixa persistente no HUD; alarmes repetem o aviso a cada 15 segundos até encerrar, lembretes a cada 60 segundos. O painel lista e encerra avisos. O JARVIS deve estar aberto e o PC acordado: não desperta computador suspenso/desligado. Avisos vencidos são recuperados ao reabrir. Nesta etapa, agendamentos são únicos.

## Estado e segurança operacional

As chaves Gemini/OpenAI são preservadas no backend. No modo local, não são usadas para interpretação, e não existe fallback pago. O orçamento diário de API não bloqueia comandos locais nem contabiliza seus tokens como tokens pagos. A voz e a transcrição continuam com os provedores locais já escolhidos.

O serviço Ollama do JARVIS é exclusivo de `127.0.0.1:11439`, com modelos em `.data/models/ollama`; não usa a porta padrão, os modelos ou processos pessoais do usuário. Credenciais são retiradas do ambiente do subprocesso. Ele é iniciado sob demanda; não instala um serviço global.

Validação: testes de persistência/reabertura, horários, disparo de alarme/encerramento (som do Windows simulado no teste), idempotência de notas, bloqueio de ações não expostas, cancelamento, isolamento de orçamento pago e fallback; navegação real em páginas de teste servidas ao Chrome oculto, com abrir, preencher, seguir link, voltar, ler e rolar. Nenhuma aba pessoal foi anexada. `scripts/validate_basic_tools.py` repete o ensaio de navegador e a consulta de tempo.

O servidor real também concluiu `Qual o tempo agora?` em cerca de 1,3 s sem inferência e `Me mostre os lembretes que estão agendados` com uma inferência local, ambos com zero chamadas pagas. O ensaio desativou temporariamente a fala, restaurou-a e removeu somente seus próprios registros. O painel foi carregado no Chrome oculto, sem erros JavaScript, confirmando Qwen local, voz aprovada, Whisper e G522 selecionados. Captura: `.data/local-mode-panel.png`.

Correção após o primeiro teste do usuário: a frase transcrita `Javis, abro o Google, entre no YouTube e toque uma música do Guns and Roses` produz navegação e reprodução; `já avisava para o youtube` produz apenas navegação. Uma interpretação do modelo não pode encerrar avisos sem pedido explícito. Testes de regressão cobrem fechamento/reabertura da janela, carregamento de requisições entre comandos, cancelamento antes de abrir e confirmação do player após o anúncio. O ensaio real oculto/silenciado em `scripts/validate_youtube.py` recuperou uma janela fechada, reproduziu `Guns N' Roses - Welcome To The Jungle` em cerca de 17,7 s e observou mais 2,07 s de avanço enquanto não havia comando. Relatório: `.data/youtube-validation.json`.

A arquitetura e as medições posteriores estão em [Ferramentas reutilizáveis](TOOLS.md). O ensaio anterior de reprodução acima é histórico; a sequência atual preserva três etapas explícitas e permite controles subsequentes sem inferência.

O modelo pequeno pode interpretar mal frases novas. Horários precisam aparecer no pedido; conteúdo de notas e rótulos de alarmes não podem ser inventados. Resultado de ferramenta com erro nunca vira confirmação de sucesso. Pedidos ambíguos devem ser reformulados. Encaminhamento ao aplicativo ChatGPT e tarefas complexas continuam fora desta etapa.

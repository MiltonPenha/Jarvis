# Reorganização do HUD — 19/10/2026

Alteração de interface em `web/index.html`, `web/style.css` e `web/app.js`. Capacidades, integrações, modelos e configuração de áudio permanecem no backend existente; não foi necessário reiniciá-lo.

## Apresentação

- A coluna de sistema foi substituída por uma faixa com **CPU e RAM em percentual**. Não há mostradores circulares nem coluna com altura reservada.
- **Detalhes do sistema** reúne núcleos/frequência, memória usada/total, armazenamento usado/livre/total, uptime e estação. **Comandos rápidos** mantém os sete atalhos existentes em um disclosure nativo, recolhido inicialmente.
- O corpo tem duas áreas: visual JARVIS com pedido reconhecido e voz; conteúdo da tarefa e conversa na lateral. Cores, famílias tipográficas, animação e identidades dos controles existentes foram reaproveitadas.
- O conteúdo ocupa apenas uma linha quando vazio. Uma seleção abre seus detalhes uma vez; atualizações posteriores respeitam o recolhimento manual. Encontrado, selecionado, abrindo, solicitado ao Windows, confirmado e aguardando escolha continuam usando os eventos existentes. Detalhes de mídia aparecem quando há observação relevante do player.
- Um novo pedido limpa a seleção anterior sem inventar conteúdo para a nova tarefa. O estado da mídia continua separado. Uma nova conversa limpa o contexto visual correspondente.
- O estado principal aparece no indicador superior, sem cópias no centro e no cartão do pedido. O pedido atual fica no cartão de reconhecimento; sua entrada correspondente no histórico não é mostrada em duplicidade. Ao chegar o próximo pedido, o anterior volta a aparecer no histórico na posição original.
- CPU/RAM atualizam somente seus textos. Os disclosures, histórico, canvas e controles não são reconstruídos a cada atualização. Percentuais têm largura numérica estável.
- No celular, o pedido fica antes do visual central, com conteúdo e conversa abaixo. Equalizador, títulos longos e campo de comando se adaptam à largura. Detalhes têm rolagem quando necessário, mantendo controles acessíveis em janelas baixas.

## Comparação medida em 1440×900

| Elemento | Antes | Depois |
| --- | --- | --- |
| Sistema recolhido | Coluna de 310×806 px | Faixa de 1440×47 px |
| Área ocupada pelo sistema | 249.860 px² | 67.680 px², redução de 72,9% |
| Visual central | 340×180 px | 324×324 px, aumento de 71,5% na área |
| Largura da conversa | 370 px | 599 px, aumento de 61,9% |
| Conteúdo vazio | 177 px de altura | 53 px de altura |

Medidas da apresentação recolhida, não de custo de CPU/GPU. Abrir detalhes auxiliares utiliza espaço proporcional ao conteúdo; fechar devolve esse espaço ao corpo principal.

Capturas locais:

- [Antes, em espera](../.data/validation/layout-reorganization/before/idle-desktop.png).
- [Depois, em espera](../.data/validation/layout-reorganization/after/1440-idle.png).
- [Execução com conteúdo simulado](../.data/validation/layout-reorganization/after/1440-executing.png).
- [Detalhes e atalhos expandidos](../.data/validation/layout-reorganization/after/1440-auxiliaries.png).
- [Celular, pedido de esclarecimento simulado](../.data/validation/layout-reorganization/after/390-waiting.png).

## Validação executada

- **18 testes JavaScript aprovados**, incluindo atualização de telemetria sem reconstrução, preservação do recolhimento manual e limpeza de conteúdo entre tarefas.
- `scripts/validate_layout.py`: renderização real em Chrome headless isolado, com eventos de tarefa simulados. **24 combinações de estado/janela**: escuta, processamento, execução, sucesso, erro e esclarecimento em **1440×900, 1280×720, 1000×800 e 390×844**. Espera também foi capturada em todos os tamanhos.
- Disclosures abertos/fechados por clique, atualização de métricas mantendo nós e abertura existentes, conteúdo expandido/recolhido, títulos longos, ausência de transbordamento horizontal e acesso ao campo/botão de envio, inclusive com auxiliares expandidos.
- Os **sete atalhos** foram clicados nos quatro tamanhos. O teste interceptou sua fronteira de ação e verificou os destinos/argumentos; não executou aplicativos, música, captura de tela ou outras ações reais.
- `scripts/validate_feedback_hud.py` também passou: estados distintos de pedido/voz/mídia, eventos atrasados, configurações e renderização em desktop, tablet e celular.
- Inspeção visual das capturas antes/depois, de execução, esclarecimento no celular e auxiliares expandidos. Nenhum erro JavaScript de página foi observado no ensaio final.

Os ensaios não gravam microfone, sintetizam voz, conectam ao Chrome pessoal nem alteram configurações. Eventos e respostas de teste estão identificados como simulados nas capturas; essa validação é da interface, não uma nova comprovação das capacidades no computador.

Relatório estruturado e capturas em `.data/validation/layout-reorganization/`. Os três arquivos de interface anteriores foram preservados em `before/` para comparação. Para repetir com o JARVIS aberto:

```powershell
node --test tests/test_model_selectors.cjs
.venv\Scripts\python.exe scripts/validate_layout.py
.venv\Scripts\python.exe scripts/validate_feedback_hud.py
```

Recarregue o painel para carregar HTML, CSS e JavaScript atualizados. Nenhuma segunda janela do JARVIS foi iniciada.

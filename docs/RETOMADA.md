# Checkpoint de desenvolvimento — 20/10/2026

Repositório: https://github.com/MiltonPenha/Jarvis

Este checkpoint preserva o código, testes, scripts de preparação/validação, corpus de avaliação e documentação acumulados até a pausa no desenvolvimento. O histórico local anterior também acompanha a publicação. Credenciais, dados pessoais, runtimes e modelos instalados ficam fora do Git.

## Estado preservado

- Assistente em português brasileiro, com contexto de tarefa, ferramentas e registro persistente de efeitos. Comandos locais não recorrem automaticamente a uma API paga.
- IA atual: Qwen3:1.7b em CPU. Transcrição: Whisper base/int8 local. Voz aprovada: Qwen local em CPU. A entrada selecionada neste computador continua sendo o G522. As preferências locais permanecem em `.data/settings.json`, fora do repositório.
- Navegação e controle de mídia no Chrome habitual mediante conexão autorizada. Busca, seleção, confirmação, reprodução, volume e sugestões usam o controlador existente. Sucesso musical exige evidência de reprodução do vídeo autorizado.
- Referências como “toque essa” usam a lista observada e a opção apresentada/selecionada; ambiguidade pede opções reais. O contexto inclui a identidade da aba do Chrome para reconexão. Ver `MEDIA_REFERENCES.md`.
- HUD com telemetria CPU/RAM compacta, detalhes e atalhos recolhíveis, conteúdo da tarefa e proteção contra eventos antigos. Ver `LAYOUT_REORGANIZATION.md`.
- Parada normal aguarda a porta livre. Workers privados órfãos são recuperados somente após validar sua identidade e a ausência do proprietário. O iniciador reutiliza o servidor ativo antes de importar os serviços pesados.

## Retomar neste computador

1. Abra a pasta do projeto e consulte o histórico Git, este arquivo e `PROGRESS.md`.
2. Inicie com `start_jarvis.bat`. Se a janela já estiver aberta, atualize-a. Para encerrar, use `stop_jarvis.bat` e aguarde a confirmação antes de iniciar novamente.
3. Confira as preferências no painel. Conecte o Chrome somente quando for testar navegação; a autorização nativa pode ser necessária. Não abra um segundo controlador sobre o mesmo perfil.
4. Use testes de texto primeiro. Novas gravações com o microfone do usuário dependem de sua disponibilidade; não são pré-requisito para testar o restante.

O script corrigido de parada da área de trabalho foi preservado em `scripts/desktop/PARAR_JARVIS.bat`. Essa cópia pressupõe que o projeto esteja na pasta `jarvis`, ao lado do script na área de trabalho. Em outros locais, use diretamente o `stop_jarvis.bat` da raiz do projeto. O atalho de inicialização atual aponta para `start_jarvis.bat`.

## Preparar outra instalação

Siga `README.md` e os scripts de preparação. `.venv`, `.runtime` e `.data/models` não estão no Git; precisam ser preparados novamente. O setup do Hermes usa o repositório oficial e a revisão indicada no README. Os scripts próprios incluem `scripts/setup_local_model.py`, `scripts/setup_voice.ps1` e `scripts/setup_qwen_voice.py`; os requisitos de cada voz estão nos documentos de áudio.

Copie `.env.example` para `.env` e configure apenas o necessário. Não publique `.env`, cookies ou chaves. A voz/transcrição local e o modelo básico local não precisam de chave paga. Provedores de nuvem continuam opcionais.

Notas, lembretes, histórico, configurações, gravações de avaliação e perfis de navegador são dados locais. Um clone do repositório não é backup desses dados. Eles continuam preservados neste computador; transfira-os separadamente apenas quando desejar, sem publicar credenciais ou sessões do navegador.

## Verificação e limites conhecidos

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
node --test tests/test_model_selectors.cjs
```

As execuções e seus limites estão em `PROGRESS.md`, `MEDIA_REFERENCES.md`, `MUSIC_EVALUATION.md` e `evaluations/music/RESULTS_2026-10-19.md`. Diferenciam testes controlados, IA real, áudio humano e YouTube real. Não houve treinamento nem alteração automática de pesos.

Na preparação desta publicação, a suíte completa passou com 255 testes Python e 20 testes JavaScript. São verificações automatizadas; essa execução não representa um novo ensaio de microfone ou reprodução no YouTube real.

A interpretação e a transcrição ainda podem exigir esclarecimento; a voz Qwen tem latência de geração em CPU, mantida por preferência do usuário. Resultados e anúncios do YouTube variam. Não considerar todos os cenários possíveis aprovados apenas porque uma bateria passou.

Última correção antes da publicação: recuperação de reinício. Passaram 29 testes focados, recuperação real de worker após término abrupto com inferência CPU/0 VRAM, encerramento com liberação das portas e nova partida com um único servidor. Os relatórios privados ficam em `.data/validation/restart-repair/` e não são publicados. O desenvolvimento está em pausa por solicitação do usuário; este documento indica o ponto de retomada.

# Jarvis

Assistente virtual local em Python, inspirado no conceito do JARVIS, com foco em:

- comandos por voz em português
- execução de tarefas locais no Windows
- integração com LLM local
- automações modulares
- arquitetura escalável

## Objetivo

Construir um assistente capaz de:

- ouvir comandos de voz
- compreender linguagem natural em português
- responder por voz
- executar ações no computador
- evoluir para automações mais complexas

## Stack inicial

- Python
- Ollama
- Qwen3.5:9b
- Faster-Whisper
- Pyttsx3
- PyAutoGUI

## Estrutura do projeto

- `audio`: captura, transcrição e voz
- `brain`: integração com LLM e interpretação
- `actions`: ações executáveis no sistema
- `core`: ciclo principal do assistente
- `memory`: contexto e persistência
- `automation`: fluxos compostos
- `integrations`: integrações futuras
- `config`: configurações centralizadas

## Status atual

Estrutura inicial do projeto em construção.
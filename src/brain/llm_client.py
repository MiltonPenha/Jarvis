from ollama import chat
from config.settings import MODEL_NAME
from utils.logger import log


SYSTEM_PROMPT = """
Você é o Jarvis, um assistente pessoal inteligente.

Responda sempre em português do Brasil.
Seja direto, claro e útil.
"""


def ask_llm(user_input: str) -> str:
    log(f"Sending to LLM: {user_input}")

    response = chat(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_input},
        ],
    )

    text = response["message"]["content"].strip()

    log(f"LLM response: {text}")

    return text
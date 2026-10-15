import logging
from typing import Optional, Tuple

from core.hermes_agent import hermes_agent
from core.memory_obsidian import obsidian_memory
from core.automation import automation_service

logger = logging.getLogger("JarvisLLM")

class LLMBrain:
    """
    Bridge orchestrator wrapping the Hermes Agent and Obsidian Memory Vault.
    """
    def __init__(self):
        self.agent = hermes_agent
        self.memory = obsidian_memory

    def ask(self, user_query: str, search_context: Optional[str] = None) -> str:
        """Processes user prompt through the Hermes Agent with Obsidian memory context."""
        speech, display, thought = self.agent.process_query(user_query, extra_context=search_context)
        return speech

    def ask_full(self, user_query: str, search_context: Optional[str] = None) -> Tuple[str, str, Optional[str]]:
        """Returns (spoken_text, display_text, thought_text)."""
        return self.agent.process_query(user_query, extra_context=search_context)

    def search_and_synthesize(self, query: str) -> str:
        """Executes a live web search, synthesizes via Hermes, and saves to Obsidian."""
        results = automation_service.web_search(query, max_results=3)
        if not results:
            return f"Fiz uma busca na rede por '{query}', porém não obtive dados conclusivos no momento, senhor."

        snippets = []
        for i, r in enumerate(results, 1):
            snippets.append(f"Fonte {i}: {r['title']}\nTrecho: {r['snippet']}\nLink: {r['url']}")

        context = "\n\n".join(snippets)
        prompt = f"O usuário solicitou uma pesquisa sobre: '{query}'. Baseando-se nas fontes fornecidas, formule uma síntese elegante e concisa em seu tom britânico característico."
        speech, display, thought = self.agent.process_query(prompt, extra_context=context)

        # Save knowledge automatically into Obsidian
        try:
            self.memory.save_knowledge(
                topic=query,
                content=f"## Síntese do JARVIS\n{speech}\n\n## Fontes Consultadas\n{context}",
                tags=["pesquisa-web", "conhecimento-geral"]
            )
        except Exception as e:
            logger.debug(f"Erro ao registrar conhecimento no Obsidian: {e}")

        return speech

    def save_user_note(self, topic: str, content: str) -> str:
        return self.memory.save_knowledge(topic, content)

    def add_user_task(self, task_text: str) -> str:
        return self.memory.add_task(task_text)

    def recall_user_memory(self, query: str) -> str:
        return self.memory.search_memory(query)

    def clear_history(self):
        self.agent.history.clear()

llm_brain = LLMBrain()

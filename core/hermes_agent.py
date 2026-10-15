import os
import re
import json
import logging
from typing import List, Dict, Any, Optional, Tuple
import httpx

from core.config import config
from core.memory_obsidian import obsidian_memory
from core.automation import automation_service
from core.music_player import music_player
from core.system_monitor import system_monitor

logger = logging.getLogger("HermesAgent")

HERMES_SYSTEM_PROMPT = f"""<|im_start|>system
You are J.A.R.V.I.S. (Just A Rather Very Intelligent System), the personal artificial intelligence created by Tony Stark.
You speak with a quintessential, refined, articulate British butler manner (Paul Bettany style). You address the user cordially as "{config.USER_NAME}".

DIRECTIVES:
1. Persona: Calm, highly intelligent, slightly witty, unfailingly loyal, refined British diction.
2. Voice-Ready Output: Your final answer will be spoken aloud by a neural TTS engine. Keep your spoken responses elegant, direct, and natural. Avoid bulky markdown tables, raw markdown URLs, or endless bullet points in the speech.
3. Language: Respond in Portuguese (or English if addressed in English), maintaining your distinguished British transatlantic tone (e.g., "Certamente, senhor", "Protocolos executados", "Às suas ordens").
4. Reasoning: You can use <thought>...</thought> tags to reason through requests, retrieve memory, or decide tool actions. Thoughts will be displayed in the holographic HUD terminal, but will NOT be spoken aloud.
5. Obsidian Memory: You have a long-term memory vault. When the user asks you to remember something, save a note, create a task, or recall past facts, use the Obsidian memory system.

AVAILABLE TOOLS:
- open_target(target: str) -> Opens any app, website, or folder (e.g. "youtube", "chrome", "discord", "notepad")
- web_search(query: str) -> Live internet search with synthesized results
- play_music(song: str) -> Searches and plays music on YouTube or Spotify
- remember_note(topic: str, content: str, tags: list[str]) -> Saves a note in the Obsidian Memory Vault
- recall_memory(query: str) -> Searches the Obsidian Memory Vault
- add_task(task: str) -> Adds a task to the Obsidian to-do list
- system_status() -> Returns CPU, RAM, disk, and uptime telemetry

When calling a tool, format it as:
<tool_call>
{{"name": "tool_name", "arguments": {{"arg": "value"}}}}
</tool_call>
<|im_end|>
"""

class HermesAgent:
    """
    Nous Hermes-inspired Agent engine featuring:
    - Thought process parsing (<thought>...</thought>)
    - Obsidian Memory integration (auto-context & recall)
    - Tool execution loop
    - Resilient multi-provider LLM backend (Ollama, Gemini, OpenAI, Pollinations Fast)
    """
    def __init__(self):
        self.history: List[Dict[str, str]] = []
        self.max_history = 10
        self._http_client = httpx.Client(timeout=25.0)

    def _execute_tool(self, name: str, args: Dict[str, Any]) -> str:
        """Executes local tool actions."""
        logger.info(f"Executando ferramenta Hermes: {name}({args})")
        try:
            if name == "open_target":
                target = args.get("target", "")
                success, msg = automation_service.open_target(target)
                return msg
            elif name == "web_search":
                query = args.get("query", "")
                results = automation_service.web_search(query, max_results=3)
                if not results:
                    return f"Nenhum resultado conclusivo para '{query}'."
                return "\n".join([f"- {r['title']}: {r['snippet']}" for r in results])
            elif name == "play_music":
                song = args.get("song", "")
                success, msg = music_player.play_music(song)
                return msg
            elif name == "remember_note":
                topic = args.get("topic", "Nota")
                content = args.get("content", "")
                tags = args.get("tags", ["jarvis-memory"])
                return obsidian_memory.save_knowledge(topic, content, tags)
            elif name == "recall_memory":
                query = args.get("query", "")
                res = obsidian_memory.search_memory(query)
                return res if res else "Nenhuma nota correspondente no cofre Obsidian."
            elif name == "add_task":
                task = args.get("task", "")
                return obsidian_memory.add_task(task)
            elif name == "system_status":
                return system_monitor.get_status_speech()
            else:
                return f"Ferramenta '{name}' desconhecida."
        except Exception as e:
            return f"Erro na execução da ferramenta {name}: {e}"

    def process_query(self, user_query: str, extra_context: Optional[str] = None) -> Tuple[str, str, Optional[str]]:
        """
        Runs the full Hermes cognitive loop.
        Returns: (spoken_text, display_text, thought_text)
        """
        # 1. Retrieve Obsidian Memory Context
        vault_profile = obsidian_memory.get_user_profile()
        vault_search = obsidian_memory.search_memory(user_query, max_results=2)

        memory_prompt = ""
        if vault_profile:
            memory_prompt += f"\n[PERFIL DO USUÁRIO NO OBSIDIAN]:\n{vault_profile}\n"
        if vault_search:
            memory_prompt += f"\n[NOTAS RELEVANTES DO COFRE OBSIDIAN]:\n{vault_search}\n"
        if extra_context:
            memory_prompt += f"\n[DADOS ADICIONAIS]:\n{extra_context}\n"

        full_prompt = (
            f"{memory_prompt}\n"
            f"[COMANDO/PERGUNTA DO {config.USER_NAME}]: {user_query}"
        )

        # 2. Query LLM Backend
        raw_response = self._query_llm(full_prompt)

        # 3. Parse <thought> tags
        thought_match = re.search(r"<thought>(.*?)</thought>", raw_response, re.DOTALL)
        thought_text = thought_match.group(1).strip() if thought_match else None
        
        # Clean response without thought tags for speech
        clean_response = re.sub(r"<thought>.*?</thought>", "", raw_response, flags=re.DOTALL).strip()

        # 4. Check and execute <tool_call>
        tool_match = re.search(r"<tool_call>\s*({.*?})\s*</tool_call>", clean_response, re.DOTALL)
        if tool_match:
            try:
                tool_data = json.loads(tool_match.group(1))
                tool_name = tool_data.get("name")
                tool_args = tool_data.get("arguments", {})
                tool_result = self._execute_tool(tool_name, tool_args)

                # Strip tool call tag from speech
                clean_response = re.sub(r"<tool_call>.*?</tool_call>", "", clean_response, flags=re.DOTALL).strip()
                if not clean_response:
                    clean_response = tool_result
            except Exception as ex:
                logger.warning(f"Erro ao parsear chamada de ferramenta Hermes: {ex}")

        # Final cleanup for TTS
        clean_speech = re.sub(r"<\|im_.*?\|>", "", clean_response).strip()
        clean_speech = re.sub(r"```.*?```", "Os detalhes foram exibidos em sua tela, senhor.", clean_speech, flags=re.DOTALL).strip()

        if not clean_speech:
            clean_speech = f"Com certeza, {config.USER_NAME}. Processamento concluído."

        # 5. Automatically log interaction to Obsidian Vault
        obsidian_memory.log_interaction(user_query, clean_speech)
        self._record_history(user_query, clean_speech)

        return clean_speech, clean_response, thought_text

    def _query_llm(self, prompt: str) -> str:
        """Queries the active LLM backend with fallbacks."""
        messages = [{"role": "system", "content": HERMES_SYSTEM_PROMPT}]
        messages.extend(self.history[-6:])
        messages.append({"role": "user", "content": prompt})

        # 1. Try Ollama (Local Hermes if active)
        try:
            r = self._http_client.get(f"{config.OLLAMA_URL}/api/tags", timeout=1.0)
            if r.status_code == 200:
                payload = {
                    "model": config.OLLAMA_MODEL,
                    "prompt": f"{HERMES_SYSTEM_PROMPT}\n\nUser: {prompt}\nJarvis:",
                    "stream": False
                }
                res = self._http_client.post(f"{config.OLLAMA_URL}/api/generate", json=payload, timeout=25.0)
                if res.status_code == 200:
                    ans = res.json().get("response", "").strip()
                    if ans:
                        return ans
        except Exception:
            pass

        # 2. Try Gemini if configured
        if config.GEMINI_API_KEY and not config.GEMINI_API_KEY.startswith("[REMOVED_LEGACY_CREDENTIAL]"):
            try:
                from google import genai
                client = genai.Client(api_key=config.GEMINI_API_KEY)
                res = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=f"{HERMES_SYSTEM_PROMPT}\n\n{prompt}"
                )
                if res.text:
                    return res.text.strip()
            except Exception as e:
                logger.warning(f"Gemini fallback error: {e}")

        # 3. Try OpenAI if configured
        if config.OPENAI_API_KEY and config.OPENAI_API_KEY.startswith("sk-"):
            try:
                from openai import OpenAI
                client = OpenAI(api_key=config.OPENAI_API_KEY)
                res = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    temperature=0.7
                )
                if res.choices[0].message.content:
                    return res.choices[0].message.content.strip()
            except Exception as e:
                logger.warning(f"OpenAI fallback error: {e}")

        # 4. Free Zero-Config Fallback (Pollinations Fast Tier)
        try:
            res = self._http_client.post(
                "https://text.pollinations.ai/",
                json={"messages": messages, "model": "openai-fast", "temperature": 0.7},
                timeout=25.0
            )
            if res.status_code == 200 and res.text:
                ans = res.text.strip()
                if ans.startswith("```") and ans.endswith("```"):
                    ans = ans.strip("`").strip()
                return ans
        except Exception as e:
            logger.error(f"Erro no fallback Pollinations: {e}")

        return f"Meus servidores neurais estão temporariamente indisponíveis no momento, {config.USER_NAME}."

    def _record_history(self, user: str, assistant: str):
        self.history.append({"role": "user", "content": user})
        self.history.append({"role": "assistant", "content": assistant})
        if len(self.history) > self.max_history * 2:
            self.history = self.history[-self.max_history * 2:]

hermes_agent = HermesAgent()

import os
import re
import glob
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

from core.config import config

class ObsidianMemory:
    """
    Long-term and episodic memory system integrated directly with an Obsidian Vault.
    Stores and retrieves memories, daily logs, knowledge graph notes, and user profiles.
    """
    def __init__(self, vault_path: Optional[str] = None):
        if vault_path:
            self.vault_dir = Path(vault_path)
        else:
            self.vault_dir = Path(config.OBSIDIAN_VAULT_PATH)
            
        self.daily_dir = self.vault_dir / "Daily"
        self.user_dir = self.vault_dir / "User"
        self.knowledge_dir = self.vault_dir / "Knowledge"
        self.tasks_dir = self.vault_dir / "Tasks"
        self.conv_dir = self.vault_dir / "Conversations"

        self._ensure_structure()

    def _ensure_structure(self):
        """Ensures all essential vault folders exist."""
        for folder in [self.vault_dir, self.daily_dir, self.user_dir, self.knowledge_dir, self.tasks_dir, self.conv_dir]:
            folder.mkdir(parents=True, exist_ok=True)

    def log_interaction(self, user_msg: str, jarvis_reply: str):
        """Appends an interaction to today's daily note in Obsidian."""
        try:
            today_str = datetime.now().strftime("%Y-%m-%d")
            daily_file = self.daily_dir / f"{today_str}.md"
            now_time = datetime.now().strftime("%H:%M:%S")

            if not daily_file.exists():
                header = (
                    f"---\n"
                    f"date: {today_str}\n"
                    f"type: daily-log\n"
                    f"tags: [daily, jarvis-log]\n"
                    f"---\n\n"
                    f"# Diário de Atividades - {today_str}\n\n"
                )
                daily_file.write_text(header, encoding="utf-8")

            entry = (
                f"### [{now_time}] Diálogo\n"
                f"- **{config.USER_NAME}**: {user_msg}\n"
                f"- **J.A.R.V.I.S.**: {jarvis_reply}\n\n"
            )
            with open(daily_file, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception as e:
            print(f"[ObsidianMemory] Erro ao gravar nota diária: {e}")

    def save_knowledge(self, topic: str, content: str, tags: Optional[List[str]] = None) -> str:
        """Creates or updates a knowledge note in the Obsidian Vault."""
        try:
            # Clean filename
            safe_topic = re.sub(r'[\\/*?:"<>|]', '', topic).strip()
            note_file = self.knowledge_dir / f"{safe_topic}.md"
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            tags_yaml = ", ".join(tags) if tags else "knowledge, ai-note"
            frontmatter = (
                f"---\n"
                f"topic: \"{safe_topic}\"\n"
                f"updated: {now_str}\n"
                f"tags: [{tags_yaml}]\n"
                f"---\n\n"
                f"# {safe_topic}\n\n"
                f"{content}\n\n"
                f"---\n"
                f"*Registrado na memória neural pelo J.A.R.V.I.S. em {now_str}*\n"
            )
            note_file.write_text(frontmatter, encoding="utf-8")
            return f"Nota [[{safe_topic}]] registrada com sucesso na memória do Obsidian."
        except Exception as e:
            return f"Erro ao salvar conhecimento: {e}"

    def add_task(self, task_text: str) -> str:
        """Appends a new task to Tasks/Tarefas.md."""
        try:
            tasks_file = self.tasks_dir / "Tarefas.md"
            now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
            if not tasks_file.exists():
                tasks_file.write_text("# 📋 Lista de Tarefas e Lembretes\n\n", encoding="utf-8")

            entry = f"- [ ] {task_text} *(Criado em: {now_str})*\n"
            with open(tasks_file, "a", encoding="utf-8") as f:
                f.write(entry)
            return f"Lembrete adicionado à sua lista de tarefas do Obsidian: '{task_text}'."
        except Exception as e:
            return f"Erro ao salvar tarefa: {e}"

    def search_memory(self, query: str, max_results: int = 3) -> str:
        """Searches across all markdown notes in the Obsidian Vault for relevant text."""
        keywords = [k.lower() for k in re.split(r'\s+', query) if len(k) > 2]
        if not keywords:
            return ""

        matches = []
        try:
            for md_file in self.vault_dir.rglob("*.md"):
                if ".obsidian" in str(md_file):
                    continue
                try:
                    text = md_file.read_text(encoding="utf-8")
                except Exception:
                    continue

                score = sum(1 for kw in keywords if kw in text.lower())
                if score > 0:
                    # Extract snippet
                    lines = [l.strip() for l in text.split("\n") if any(kw in l.lower() for kw in keywords)]
                    snippet = " | ".join(lines[:3]) if lines else text[:200]
                    rel_name = md_file.relative_to(self.vault_dir).as_posix()
                    matches.append((score, f"[[{rel_name}]]: {snippet}"))

            matches.sort(key=lambda x: x[0], reverse=True)
            results = [m[1] for m in matches[:max_results]]
            return "\n".join(results)
        except Exception as e:
            print(f"[ObsidianMemory] Erro na busca de memória: {e}")
            return ""

    def get_user_profile(self) -> str:
        """Reads user profile and preferences from Obsidian."""
        profile_content = ""
        perfil_file = self.user_dir / "Perfil.md"
        pref_file = self.user_dir / "Preferencias.md"

        if perfil_file.exists():
            try:
                profile_content += perfil_file.read_text(encoding="utf-8") + "\n"
            except Exception:
                pass

        if pref_file.exists():
            try:
                profile_content += pref_file.read_text(encoding="utf-8") + "\n"
            except Exception:
                pass

        return profile_content.strip()

    def open_vault_folder(self):
        """Opens the Obsidian Vault folder in Windows Explorer."""
        os.startfile(str(self.vault_dir))

obsidian_memory = ObsidianMemory()

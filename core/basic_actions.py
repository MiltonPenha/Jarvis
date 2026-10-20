"""Compatibility exports derived from the central contracts, without host imports."""
from core.tool_registry import TOOLS
BASIC_ACTIONS={name for name,tool in TOOLS.items() if tool.local and name not in ('open_target','system_status','play_music','media','volume')}
BASIC_EFFECTS={name for name in BASIC_ACTIONS if TOOLS[name].effect}

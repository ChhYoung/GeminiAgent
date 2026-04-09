"""
mcp/plugin.py — 插件管理器 (s19)

版本化插件加载，支持热更新。
插件是 Python 文件，需暴露 PLUGIN_META 和 setup(registry) 函数。
"""

from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from hello_agents.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

_DEFAULT_PLUGIN_DIR = Path.home() / ".agent" / "plugins"


@dataclass
class PluginMeta:
    plugin_id: str
    name: str
    version: str
    description: str = ""
    path: str = ""


class PluginManager:
    """
    插件管理器。

    用法：
        mgr = PluginManager()
        mgr.load("/path/to/my_plugin.py", registry)
        mgr.list_plugins()
        mgr.unload("my_plugin")
    """

    def __init__(self) -> None:
        self._plugins: dict[str, tuple[PluginMeta, Any]] = {}  # id → (meta, module)

    def load(self, plugin_path: str | Path, registry: "ToolRegistry") -> PluginMeta | None:
        """加载插件文件，调用其 setup(registry) 函数。"""
        p = Path(plugin_path)
        if not p.exists():
            logger.warning("Plugin not found: %s", p)
            return None

        try:
            spec = importlib.util.spec_from_file_location(p.stem, p)
            if spec is None or spec.loader is None:
                return None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # type: ignore[union-attr]

            meta_dict = getattr(module, "PLUGIN_META", {})
            meta = PluginMeta(
                plugin_id=meta_dict.get("id", p.stem),
                name=meta_dict.get("name", p.stem),
                version=meta_dict.get("version", "0.1.0"),
                description=meta_dict.get("description", ""),
                path=str(p),
            )

            setup_fn = getattr(module, "setup", None)
            if setup_fn:
                setup_fn(registry)

            self._plugins[meta.plugin_id] = (meta, module)
            logger.info("Plugin loaded: %s v%s", meta.name, meta.version)
            return meta
        except Exception as exc:
            logger.warning("Failed to load plugin %s: %s", plugin_path, exc)
            return None

    def unload(self, plugin_id: str) -> bool:
        if plugin_id in self._plugins:
            del self._plugins[plugin_id]
            logger.info("Plugin unloaded: %s", plugin_id)
            return True
        return False

    def reload(self, plugin_id: str, registry: "ToolRegistry") -> PluginMeta | None:
        if plugin_id not in self._plugins:
            logger.warning("Plugin '%s' not loaded", plugin_id)
            return None
        meta, _ = self._plugins[plugin_id]
        path = meta.path
        self.unload(plugin_id)
        return self.load(path, registry)

    def list_plugins(self) -> list[PluginMeta]:
        return [meta for meta, _ in self._plugins.values()]

    def load_from_directory(self, registry: "ToolRegistry", directory: Path | str = _DEFAULT_PLUGIN_DIR) -> int:
        """扫描目录，加载所有 .py 插件文件。"""
        d = Path(directory)
        if not d.exists():
            return 0
        count = 0
        for py in d.glob("*.py"):
            if self.load(py, registry):
                count += 1
        return count

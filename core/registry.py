from __future__ import annotations

import importlib
import inspect
import pkgutil
import time
import uuid
from pathlib import Path
from typing import Any

from .context import Context
from .errors import PluginError
from .plugin import Plugin


class PluginRegistry:
    def __init__(self, context: Context) -> None:
        self.context = context
        self._plugins: dict[str, Plugin] = {}
        self._order: list[str] = []
        self._class_specs: dict[str, dict[str, Any]] = {}
        self._class_order: list[str] = []

    def register(self, plugin: Plugin) -> None:
        if plugin.name in self._plugins or plugin.name in self._class_specs:
            raise PluginError(f"Plugin already registered: {plugin.name}")
        missing = [d for d in plugin.dependencies if d not in self._plugins and d not in self.context.plugins]
        if missing:
            raise PluginError(f"Plugin {plugin.name!r} has missing dependencies: {', '.join(missing)}")
        plugin.register(self.context)
        self._plugins[plugin.name] = plugin
        self._order.append(plugin.name)
        self.context.plugins[plugin.name] = plugin

    def register_class(self, cls: type, **kwargs: Any) -> None:
        name = getattr(cls, "name", cls.__name__.lower())
        if name in self._plugins or name in self._class_specs:
            raise PluginError(f"Plugin already registered: {name}")
        self._class_specs[name] = {
            "class": cls,
            "kwargs": kwargs,
            "dependencies": getattr(cls, "dependencies", ()),
        }
        self._class_order.append(name)

    def resolve_all(self) -> None:
        available = set(self._plugins.keys()) | set(self.context.plugins.keys()) | set(self._class_specs.keys())
        for name, spec in self._class_specs.items():
            for dep_name in spec["dependencies"]:
                if dep_name not in available:
                    raise PluginError(
                        f"Plugin {name!r} has unresolved dependency {dep_name!r}. "
                        f"Available: {sorted(available)}"
                    )

        order = self._topological_sort()
        for name in order:
            spec = self._class_specs[name]
            cls = spec["class"]
            kwargs = dict(spec["kwargs"])

            try:
                sig = inspect.signature(cls.__init__)
                params = [p for p in sig.parameters if p != "self"]
            except (ValueError, TypeError):
                params = []

            for dep_name in spec["dependencies"]:
                if dep_name in self.context.plugins and dep_name in params:
                    kwargs[dep_name] = self.context.plugins[dep_name]

            try:
                instance = cls(**kwargs)
            except Exception as exc:
                raise PluginError(f"Failed to instantiate plugin {name!r}: {exc}") from exc
            instance.register(self.context)
            self._plugins[name] = instance
            self._order.append(name)
            self.context.plugins[name] = instance

    def start_all(self) -> None:
        self.resolve_all()
        started: list[str] = []
        last_name = "<unknown>"
        try:
            for name in self._order:
                last_name = name
                self._plugins[name].start()
                started.append(name)
        except Exception as exc:
            for name in reversed(started):
                try:
                    self._plugins[name].stop()
                except Exception:
                    pass
            raise PluginError(f"Plugin startup failed: {last_name}") from exc

        health_monitor = self._plugins.get("health_monitoring")
        if health_monitor is not None:
            for name in self._plugins:
                health_monitor.register_plugin(name)

    def stop_all(self) -> None:
        for name in reversed(self._order):
            self._plugins[name].stop()

    def unregister(self, name: str) -> None:
        plugin = self._plugins.get(name)
        if plugin is None:
            raise PluginError(f"Unknown plugin: {name}")
        dependents = [o.name for o in self._plugins.values() if name in o.dependencies]
        if dependents:
            raise PluginError(f"Cannot unregister {name!r}; dependents: {', '.join(dependents)}")
        plugin.stop()
        plugin.unregister()
        del self._plugins[name]
        self._order.remove(name)
        self.context.plugins.pop(name, None)

    def get(self, name: str) -> Plugin:
        try:
            return self._plugins[name]
        except KeyError as exc:
            raise PluginError(f"Unknown plugin: {name}") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(self._order)

    def verify_health(self) -> dict[str, Any]:
        health_monitor = self._plugins.get("health_monitoring")
        if health_monitor is None:
            return {}
        return {name: status.healthy for name, status in health_monitor.check_all().items()}

    def verify_contracts(self) -> list[Any]:
        contracts = self._plugins.get("formal_contracts")
        if contracts is None:
            return []
        all_violations = contracts.validate_all()
        flat: list[Any] = []
        for violations in all_violations.values():
            flat.extend(violations)
        return flat

    def validate_config(self, cls: type, config: dict[str, Any]) -> list[str]:
        schema = getattr(cls, "__config_schema__", {})
        errors: list[str] = []
        required = schema.get("required", [])
        for key in required:
            if key not in config:
                errors.append(f"Missing required config key: {key}")
        return errors

    def reload(self, name: str) -> None:
        if name not in self._plugins:
            raise PluginError(f"Cannot reload unknown plugin: {name}")
        old = self._plugins[name]
        old.stop()
        old.unregister()
        spec = self._class_specs.get(name)
        if spec is None:
            raise PluginError(f"No class spec for plugin: {name}")
        cls = spec["class"]
        kwargs = dict(spec["kwargs"])
        for dep_name in spec["dependencies"]:
            if dep_name in self.context.plugins:
                kwargs[dep_name] = self.context.plugins[dep_name]
        instance = cls(**kwargs)
        instance.register(self.context)
        self._plugins[name] = instance
        self.context.plugins[name] = instance
        try:
            instance.start()
        except Exception as exc:
            raise PluginError(f"Plugin reload failed: {name}") from exc

    def collect_metrics(self) -> dict[str, Any]:
        results: dict[str, Any] = {}
        for name, plugin in self._plugins.items():
            try:
                results[name] = plugin.get_metrics()
            except Exception:
                results[name] = {}
        return results

    def discover(self, package_path: str = "plugins", config: dict[str, dict[str, Any]] | None = None) -> None:
        """Auto-discover Plugin subclasses under a dotted package path."""
        config = config or {}
        try:
            package = importlib.import_module(package_path)
        except Exception:
            return

        pkg_dir = Path(getattr(package, "__file__", "")).parent
        for finder, module_name, is_pkg in pkgutil.walk_packages([str(pkg_dir)], prefix=package_path + "."):
            if module_name.endswith(".__init__"):
                continue
            try:
                module = importlib.import_module(module_name)
            except Exception:
                continue
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if not isinstance(attr, type):
                    continue
                if attr_name in {"Plugin", "EventDrivenPlugin"}:
                    continue
                try:
                    is_plugin = issubclass(attr, Plugin)
                except TypeError:
                    continue
                if not is_plugin:
                    continue
                name = getattr(attr, "name", attr_name.lower())
                if name in self._plugins or name in self._class_specs:
                    continue
                kwargs = dict(config.get(name, {}))
                self._class_specs[name] = {
                    "class": attr,
                    "kwargs": kwargs,
                    "dependencies": getattr(attr, "dependencies", ()),
                }
                self._class_order.append(name)

    def _topological_sort(self) -> list[str]:
        graph: dict[str, list[str]] = {}
        for name, spec in self._class_specs.items():
            internal_deps = [d for d in spec["dependencies"] if d in self._class_specs]
            graph[name] = internal_deps

        if not graph:
            return list(self._class_specs.keys())

        in_degree = {name: len(deps) for name, deps in graph.items()}
        dependents: dict[str, list[str]] = {name: [] for name in graph}
        for name, deps in graph.items():
            for dep in deps:
                if dep in dependents:
                    dependents[dep].append(name)

        queue = [name for name, degree in in_degree.items() if degree == 0]
        result: list[str] = []

        while queue:
            node = queue.pop(0)
            result.append(node)
            for dependent in dependents.get(node, []):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(result) != len(graph):
            raise PluginError("Circular dependency detected in class-based plugins")

        return result

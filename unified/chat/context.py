from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from unified.schema import QuerySource


class ChatMessage(BaseModel):
    role: str
    content: str
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")


class ModuleContext(BaseModel):
    module_name: str
    source: QuerySource = QuerySource.HYBRID
    description: str = ""
    starter_questions: list[str] = Field(default_factory=list)
    conversation_history: list[ChatMessage] = Field(default_factory=list)

    def add_message(self, role: str, content: str) -> None:
        self.conversation_history.append(ChatMessage(role=role, content=content))


class SourceAwareModuleContextManager:
    def __init__(self) -> None:
        self._modules: dict[str, ModuleContext] = {}
        self._active_module: str | None = None

    def register_module(
        self,
        name: str,
        source: QuerySource = QuerySource.HYBRID,
        description: str = "",
        starter_questions: list[str] | None = None,
    ) -> ModuleContext:
        context = ModuleContext(
            module_name=name,
            source=source,
            description=description,
            starter_questions=starter_questions or [],
        )
        self._modules[name] = context
        if self._active_module is None:
            self._active_module = name
        return context

    def switch_module(self, name: str) -> ModuleContext:
        if name not in self._modules:
            raise KeyError(name)
        self._active_module = name
        return self._modules[name]

    @property
    def active(self) -> ModuleContext | None:
        return self._modules.get(self._active_module) if self._active_module else None

    @property
    def available_modules(self) -> list[str]:
        return list(self._modules.keys())


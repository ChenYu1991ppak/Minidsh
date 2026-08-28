"""配置数据模型与默认值。

模型配置对齐 CodeBuddy 的 models.json：每个模型条目自带 id/name/vendor/url/
apiKey 与能力位（supportsToolCall/supportsReasoning/supportsImages）。
harness 设置（storage/compaction/tools）来自独立的 settings.json。
"""
from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["Config", "ModelSpec"]


@dataclass
class ModelSpec:
    """单个模型条目（对齐 CodeBuddy models.json 的 ``models[]`` 结构）。"""

    id: str
    name: str = ""
    vendor: str = ""
    url: str = ""                    # OpenAI 兼容 base_url；空 = 未配置，该模型不可用
    api_key: str = ""                # 内嵌密钥；空 = 未配置
    supports_tool_call: bool = True
    supports_reasoning: bool = False
    supports_images: bool = False
    temperature: float | None = None


@dataclass
class Config:
    """合并后的配置：模型列表 + harness 设置。"""

    models: list[ModelSpec] = field(default_factory=list)
    available_models: list[str] = field(default_factory=list)
    current_model: str | None = None     # currentModel 字段值（未解析时）
    storage: str = "jsonl"
    context_window: int = 8000
    compaction_threshold_ratio: float = 0.8
    allowed_tools: list[str] | None = None   # None = 全部内置工具

    def find(self, model_id: str) -> ModelSpec | None:
        for m in self.models:
            if m.id == model_id:
                return m
        return None

    @property
    def current_model_id(self) -> str | None:
        """当前生效的模型 id：currentModel 字段 > availableModels 首位。"""
        if self.current_model:
            return self.current_model
        if self.available_models:
            return self.available_models[0]
        return None

    @property
    def current(self) -> ModelSpec | None:
        mid = self.current_model_id
        return self.find(mid) if mid else None
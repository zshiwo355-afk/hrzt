"""Pydantic 请求/响应模型。"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class AttachmentLite(BaseModel):
    id: str
    name: str = ""
    category: str = "document"


class HistoryMessageItem(BaseModel):
    role: str
    text: str = ""
    attachments: list[AttachmentLite] = Field(default_factory=list)
    has_image_result: bool = False


class ChatRequest(BaseModel):
    conversation_id: int
    model: str
    reasoning_mode: Optional[str] = None
    prompt: str
    system_prompt: Optional[str] = None
    use_rag: bool = False
    use_web_search: bool = False
    rag_query: Optional[str] = None
    attachment_ids: list[str] = Field(default_factory=list)
    summary: str = ""
    history_messages: list[HistoryMessageItem] = Field(default_factory=list)
    image_model: Optional[str] = None
    image_size: str = "1024x1024"
    image_mode: Optional[str] = None


class ImageRequest(BaseModel):
    model: str
    prompt: str
    size: str = "1024x1024"
    n: int = 1
    attachment_ids: list[str] = Field(default_factory=list)
    summary: str = ""
    history_messages: list[HistoryMessageItem] = Field(default_factory=list)


class VideoRequest(BaseModel):
    model: str
    prompt: str
    attachment_ids: list[str] = Field(default_factory=list)
    summary: str = ""
    history_messages: list[HistoryMessageItem] = Field(default_factory=list)


class SummarizeHistoryRequest(BaseModel):
    mode: str
    current_summary: str = ""
    history_messages: list[HistoryMessageItem] = Field(default_factory=list)


class TaskCreateRequest(BaseModel):
    mode: str
    model: str
    reasoning_mode: Optional[str] = None
    prompt: str
    size: Optional[str] = "1024x1024"
    n: int = 1
    conversation_id: Optional[int] = None
    artifact_type: Optional[str] = None
    attachment_ids: list[str] = Field(default_factory=list)
    summary: str = ""
    history_messages: list[HistoryMessageItem] = Field(default_factory=list)
    image_mode: Optional[str] = None
    image_intent: Optional[str] = None
    reference_source: Optional[str] = None
    image_intent_confidence: float = 0.0
    use_rag: bool = False
    use_web_search: bool = False


class OutputIntentRequest(BaseModel):
    prompt: str
    mode: str = "text"


class OutputIntentResponse(BaseModel):
    output_mode: str = "chat"
    confidence: float = 0.0
    should_use_task: bool = False
    artifact_type: Optional[str] = None
    reason: str = ""


class PPTTableBlock(BaseModel):
    columns: list[str] = Field(default_factory=list)
    rows: list[list[object]] = Field(default_factory=list)


class PPTImageBlock(BaseModel):
    title: str = ""
    caption: str = ""
    image_hint: str = ""


class PPTSlide(BaseModel):
    type: str = "content"
    title: str = ""
    subtitle: str = ""
    bullets: list[str] = Field(default_factory=list)
    paragraphs: list[str] = Field(default_factory=list)
    table: Optional[PPTTableBlock] = None
    image: Optional[PPTImageBlock] = None
    notes: str = ""


class PPTDocument(BaseModel):
    title: str = ""
    subtitle: str = ""
    theme_hint: str = ""
    slides: list[PPTSlide] = Field(default_factory=list)


class ConversationCreateRequest(BaseModel):
    mode: str = "text"
    title: str = "新建聊天"
    model: str = ""
    project_id: Optional[int] = None


class ConversationUpdateRequest(BaseModel):
    title: str = ""


class ConversationProjectRequest(BaseModel):
    project_id: Optional[int] = None


class ProjectCreateRequest(BaseModel):
    name: str = "新项目"


class ProjectUpdateRequest(BaseModel):
    name: str = ""


class ClientStateRequest(BaseModel):
    state: dict = Field(default_factory=dict)
    fingerprint: str = ""
    updated_at: str = ""

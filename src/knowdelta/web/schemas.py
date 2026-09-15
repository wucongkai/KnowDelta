from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from knowdelta.models import Note, Transcript

Mode = Literal["extractive", "llm", "vision"]
Status = Literal["queued", "running", "completed", "failed", "cancelled"]


class JobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=10, max_length=2048)
    mode: Mode = "extractive"
    language: str = Field(default="zh", pattern=r"^[a-z]{2,3}$")
    asr_model: Literal["base", "small", "medium"] = "small"
    asr_prompt: str = Field(default="", max_length=500)


class JobView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    source_url: str | None
    source_name: str
    mode: Mode
    status: Status
    stage: str
    progress: int
    attempt: int
    error: str | None
    author: str
    duration_ms: int
    section_count: int
    image_count: int
    cover_frame_id: str | None
    created_at: datetime
    updated_at: datetime


class JobList(BaseModel):
    items: list[JobView]


class NoteFrame(BaseModel):
    frame_id: str
    timestamp_ms: int


class NoteView(BaseModel):
    job: JobView
    note: Note
    transcript: Transcript
    frames: list[NoteFrame]
    video_available: bool


class Capabilities(BaseModel):
    text_model_ready: bool
    vision_model_ready: bool
    text_model: str | None
    vision_model: str | None
    asr_available: bool
    max_upload_mb: int


class Health(BaseModel):
    status: str

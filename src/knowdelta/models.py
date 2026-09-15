from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Segment(Record):
    segment_id: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: str = Field(min_length=1)
    source: Literal["subtitle", "asr"]

    @model_validator(mode="after")
    def ordered(self):
        if self.end_ms <= self.start_ms:
            raise ValueError("字幕结束时间必须晚于开始时间")
        return self


class Media(Record):
    source_id: str
    source_url: str | None = None
    title: str
    author: str = ""
    part: int = Field(default=1, ge=1)
    duration_ms: int = Field(gt=0)
    video_path: str
    subtitle_paths: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class Transcript(Record):
    segments: list[Segment] = Field(min_length=1)
    language: str
    origin: str
    warnings: list[str] = Field(default_factory=list)


class Frame(Record):
    frame_id: str = Field(pattern=r"^frame_[0-9]{9,}$")
    timestamp_ms: int = Field(ge=0)
    asset_path: str
    sharpness: float


class Chapter(Record):
    chapter_id: str
    title: str
    segment_ids: list[str] = Field(min_length=1)


class Paragraph(Record):
    text: str = Field(min_length=1, max_length=12000)
    source_segment_ids: list[str] = Field(min_length=1)


class Illustration(Record):
    frame_id: str
    caption: str = Field(min_length=1, max_length=1000)


class Section(Record):
    title: str = Field(min_length=1, max_length=200)
    paragraphs: list[Paragraph] = Field(min_length=1, max_length=150)
    images: list[Illustration] = Field(default_factory=list, max_length=3)


class Note(Record):
    title: str
    mode: Literal["extractive", "llm", "vision"]
    sections: list[Section] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)

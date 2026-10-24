import shutil

import pytest
from PIL import Image
from pypdf import PdfReader

from knowdelta.pdf_exporter import build_document, content_version, render_pdf
from knowdelta.pipeline import Options, run
from knowdelta.storage import PipelineError, read_json, write_json


@pytest.fixture
def note_export(local_input, tmp_path):
    video, subtitles = local_input
    return run(Options(video=video, subtitles=subtitles, output=tmp_path / "jobs", extractive=True))


def test_pdf_offline_chinese_images_links_and_embedded_font(note_export, tmp_path):
    sources = read_json(note_export / "sources.json")
    sources["source_url"] = "https://www.bilibili.com/video/BV1p5qhYsE4f/?p=1"
    write_json(note_export / "sources.json", sources)
    pdf = tmp_path / "output.pdf"
    render_pdf(note_export, pdf, content_version(note_export))
    # A copied PDF remains self-contained; no assets are copied alongside it.
    copied = tmp_path / "independent" / "note.pdf"
    copied.parent.mkdir()
    shutil.copy2(pdf, copied)
    reader = PdfReader(copied)
    text = "".join(page.extract_text() for page in reader.pages)
    assert "客户端连接到数据库服务器" in text
    assert "KnowDelta" in text and "来源" in text
    assert sum(len(page.images) for page in reader.pages) >= 2
    fonts = [
        font.get_object() for page in reader.pages for font in page["/Resources"]["/Font"].values()
    ]
    assert fonts and all(font.get("/ToUnicode") for font in fonts)
    for font in fonts:
        descriptor = font["/DescendantFonts"][0].get_object()["/FontDescriptor"]
        assert any(key in descriptor for key in ["/FontFile", "/FontFile2", "/FontFile3"])
    links = [
        a.get_object().get("/A", {}).get("/URI", "")
        for page in reader.pages
        for a in page.get("/Annots", [])
    ]
    assert any("&t=" in link for link in links)
    assert str(note_export) not in text


def test_missing_corrupt_or_changed_images_never_publish_pdf(note_export, tmp_path):
    expected = content_version(note_export)
    first = next((note_export / "assets").glob("*.jpg"))
    first.write_bytes(b"broken")
    with pytest.raises(PipelineError, match="内容已变化"):
        render_pdf(note_export, tmp_path / "bad.pdf", expected)
    with pytest.raises(PipelineError, match="截图损坏"):
        build_document(note_export)
    first.unlink()
    with pytest.raises(PipelineError, match="不存在"):
        content_version(note_export)
    assert not (tmp_path / "bad.pdf").exists()


def test_no_images_and_tall_image_export(note_export, tmp_path):
    note = read_json(note_export / "note.json")
    note["sections"][0]["images"] = []
    write_json(note_export / "note.json", note)
    pdf = tmp_path / "no-images.pdf"
    render_pdf(note_export, pdf, content_version(note_export))
    assert not any(page.images for page in PdfReader(pdf).pages)
    sources = read_json(note_export / "sources.json")
    frame = sources["frames"][0]
    path = note_export / frame["asset_path"]
    Image.new("RGB", (300, 4000), "#aacdbb").save(path)
    note["sections"][0]["images"] = [{"frame_id": frame["frame_id"], "caption": "高图测试" * 100}]
    write_json(note_export / "note.json", note)
    render_pdf(note_export, pdf, content_version(note_export))
    reader = PdfReader(pdf)
    assert any(page.images for page in reader.pages)
    assert "高图测试" in "".join(page.extract_text() for page in reader.pages)


def test_plain_text_cannot_inject_external_pdf_resources(note_export):
    note = read_json(note_export / "note.json")
    note["title"] = '<img src="http://127.0.0.1/private">'
    write_json(note_export / "note.json", note)
    document, resources = build_document(note_export)
    assert "&lt;img" in document
    assert not any("127.0.0.1" in url for url in resources)
    assert all(isinstance(resource["string"], bytes) for resource in resources.values())

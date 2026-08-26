from types import SimpleNamespace

from app.services.chat_payloads import attachments_contain_images, build_message_content


def test_attachments_contain_images_detects_image_mime_and_data_url():
    assert attachments_contain_images(
        [
            SimpleNamespace(filename="photo.png", mime_type="image/png", data_url=None),
            SimpleNamespace(filename="scan.txt", mime_type="text/plain", data_url=None),
        ]
    )
    assert attachments_contain_images(
        [SimpleNamespace(filename="poster.bin", mime_type="application/octet-stream", data_url="data:image/jpeg;base64,abc")]
    )
    assert not attachments_contain_images(
        [SimpleNamespace(filename="notes.txt", mime_type="text/plain", data_url=None)]
    )


def test_build_message_content_uses_image_parts_only_when_enabled():
    attachment = SimpleNamespace(
        filename="poster.png",
        mime_type="image/png",
        data_url="data:image/png;base64,abc123",
        ocr_text="Affiche de conférence",
    )

    content_with_images = build_message_content("Describe this", [attachment], include_images=True)
    assert isinstance(content_with_images, list)
    assert any(part.get("type") == "image_url" for part in content_with_images)
    assert any("Affiche de conférence" in part.get("text", "") for part in content_with_images if part.get("type") == "text")

    content_without_images = build_message_content("Describe this", [attachment], include_images=False)
    assert isinstance(content_without_images, str)
    assert "image_url" not in content_without_images
    assert "Affiche de conférence" in content_without_images

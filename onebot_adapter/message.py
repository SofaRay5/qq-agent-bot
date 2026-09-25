"""Extract replyable text from OneBot array-form messages."""

from typing import Any, NamedTuple

from onebot_adapter.event import GroupMessageEvent, PrivateMessageEvent


class ImageRef(NamedTuple):
    url: str
    file_size: int | None


def _segments_for_reply(
    event: PrivateMessageEvent | GroupMessageEvent,
) -> list[dict[str, Any]]:
    if isinstance(event, PrivateMessageEvent):
        return event.message
    for index, segment in enumerate(event.message):
        data = segment.get("data")
        if (
            segment.get("type") == "at"
            and isinstance(data, dict)
            and str(data.get("qq")) == str(event.self_id)
        ):
            return event.message[index + 1 :]
    return []


def text_for_reply(event: PrivateMessageEvent | GroupMessageEvent) -> str | None:
    """Return private text or text following the bot mention in a group."""
    parts: list[str] = []
    for segment in _segments_for_reply(event):
        data = segment.get("data")
        if segment.get("type") == "text" and isinstance(data, dict):
            value = data.get("text")
            if isinstance(value, str):
                parts.append(value)
    return "".join(parts).strip() or None


def image_for_reply(event: PrivateMessageEvent | GroupMessageEvent) -> ImageRef | None:
    """Return the first ordinary image eligible for a reply."""
    for segment in _segments_for_reply(event):
        if segment.get("type") != "image":
            continue
        raw_data = segment.get("data")
        data = raw_data if isinstance(raw_data, dict) else {}
        if data.get("type") == "flash":
            continue
        size = data.get("file_size")
        try:
            file_size = (
                int(size)
                if isinstance(size, (str, int)) and str(size).isascii() and str(size).isdigit()
                else None
            )
        except ValueError:
            file_size = None
        url = data.get("url")
        return ImageRef(url if isinstance(url, str) else "", file_size)
    return None

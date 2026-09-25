"""Extract replyable text from OneBot array-form messages."""

from typing import Any, NamedTuple

from onebot_adapter.event import GroupMessageEvent, PrivateMessageEvent


class ImageRef(NamedTuple):
    url: str
    file_size: int | None


class MessageContent(NamedTuple):
    text: str | None
    image: ImageRef | None
    mentioned: bool
    reply_to: int | None


def _bot_mention_index(event: PrivateMessageEvent | GroupMessageEvent) -> int | None:
    if isinstance(event, PrivateMessageEvent):
        return None
    for index, segment in enumerate(event.message):
        data = segment.get("data")
        if (
            segment.get("type") == "at"
            and isinstance(data, dict)
            and str(data.get("qq")) == str(event.self_id)
        ):
            return index
    return None


def _text(segments: list[dict[str, Any]]) -> str | None:
    parts: list[str] = []
    for segment in segments:
        data = segment.get("data")
        if segment.get("type") == "text" and isinstance(data, dict):
            value = data.get("text")
            if isinstance(value, str):
                parts.append(value)
    return "".join(parts).strip() or None


def _image(segments: list[dict[str, Any]]) -> ImageRef | None:
    for segment in segments:
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


def _reply_target(segments: list[dict[str, Any]]) -> int | None:
    for segment in segments:
        data = segment.get("data")
        if segment.get("type") != "reply" or not isinstance(data, dict):
            continue
        value = data.get("id")
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            continue
        text = str(value)
        if not text.isascii() or not text.isdigit():
            continue
        try:
            return int(text)
        except ValueError:
            continue
    return None


def content_for_event(event: PrivateMessageEvent | GroupMessageEvent) -> MessageContent:
    """Extract text, image and trigger metadata from one message event."""
    mention_index = _bot_mention_index(event)
    if mention_index is None:
        mentioned = False
        selected = event.message
    else:
        mentioned = True
        selected = event.message[mention_index + 1 :]
    return MessageContent(
        text=_text(selected),
        image=_image(selected),
        mentioned=mentioned,
        reply_to=_reply_target(event.message),
    )


def text_for_reply(event: PrivateMessageEvent | GroupMessageEvent) -> str | None:
    """Return private text or text following the bot mention in a group."""
    content = content_for_event(event)
    if isinstance(event, GroupMessageEvent) and not content.mentioned:
        return None
    return content.text


def image_for_reply(event: PrivateMessageEvent | GroupMessageEvent) -> ImageRef | None:
    """Return the first ordinary image eligible for a reply."""
    content = content_for_event(event)
    if isinstance(event, GroupMessageEvent) and not content.mentioned:
        return None
    return content.image

"""Media operations."""


def detect_image_mime(data: bytes) -> str | None:
    """根据 Magic Bytes 检测 Image MIME Type，忽略 File Extension。

    当前识别 PNG、JPEG、GIF 与 WEBP；未知或数据过短时返回 `None`。使用内容签名可避免仅凭用户提供的
    后缀误判格式，但这里只做轻量 Header Check，不验证整张图片是否完整、可解码或安全。
    """
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None

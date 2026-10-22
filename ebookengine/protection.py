"""Distinguish EPUB font obfuscation from unsupported content encryption.

IDPF font obfuscation is not DRM. Do not remove encryption.xml or modify the
obfuscated resources; unknown algorithms and nonfont targets remain blockers.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit
from zipfile import ZipFile

from lxml import etree

from .core import _safe_path

FONT_OBFUSCATION = "http://www.idpf.org/2008/embedding"
_FONT_MIME = frozenset({
    "font/ttf", "font/otf", "application/vnd.ms-opentype",
    "application/font-sfnt", "application/x-font-ttf", "application/x-font-opentype",
})


def is_font_obfuscation_only(source) -> bool:
    """True only when every encrypted entry is IDPF-obfuscated manifest font."""
    font_paths = {
        source.paths[ident] for ident, item in source.items.items()
        if item.get("media-type") in _FONT_MIME
        and (item.get("href") or "").lower().endswith((".ttf", ".otf"))
    }
    try:
        with ZipFile(BytesIO(source.raw)) as archive:
            if "META-INF/encryption.xml" not in archive.namelist():
                return False
            root = etree.fromstring(
                archive.read("META-INF/encryption.xml"),
                parser=etree.XMLParser(resolve_entities=False, load_dtd=False,
                                       no_network=True, recover=False)
            )
            entries = root.xpath('//*[local-name()="EncryptedData"]')
            if not entries:
                return False
            for entry in entries:
                methods = entry.xpath('./*[local-name()="EncryptionMethod"]')
                refs = entry.xpath('.//*[local-name()="CipherReference"]')
                if len(methods) != 1 or len(refs) != 1:
                    return False
                if methods[0].get("Algorithm") != FONT_OBFUSCATION:
                    return False
                uri = refs[0].get("URI") or ""
                parsed = urlsplit(uri)
                if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
                    return False
                if _safe_path(unquote(parsed.path)) not in font_paths:
                    return False
            return True
    except (OSError, ValueError, KeyError, etree.XMLSyntaxError):
        return False

"""Rebuild the tracked synthetic DOCX fixtures; never reads private sources."""

from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED
from docx import Document

ROOT = Path(__file__).resolve().parents[1]


def generate(root=ROOT / "examples/control"):
    sources = json.loads((root / "sources.json").read_text())
    for version, documents in sources.items():
        (root / version).mkdir(parents=True, exist_ok=True)
        for name, lines in documents.items():
            doc = Document()
            doc.core_properties.title = "ORG-X synthetic control"
            doc.core_properties.author = "ORG-X"
            for line in lines:
                doc.add_paragraph(line)
            source = BytesIO()
            doc.save(source)
            # Stable ZIP metadata makes fixture regeneration byte-for-byte repeatable.
            with ZipFile(source) as incoming, ZipFile(
                root / version / name, "w", ZIP_DEFLATED
            ) as output:
                for item in sorted(incoming.namelist()):
                    info = ZipInfo(item, date_time=(2020, 1, 1, 0, 0, 0))
                    info.compress_type = ZIP_DEFLATED
                    output.writestr(info, incoming.read(item))


if __name__ == "__main__":
    generate()

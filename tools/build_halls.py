"""One-off: tools/Shaadi.js -> backend/halls.json.

The venue dataset ships as a JS module (object literals, unquoted keys). This pulls the six fields
the quotation flow needs and writes plain JSON, so the API never has to parse JavaScript.

    py tools/build_halls.py
"""
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "tools" / "Shaadi.js"
OUT = ROOT / "backend" / "halls.json"

FIELD = re.compile(r'(\w+)\s*:\s*("(?:[^"\\]|\\.)*"|[-\d.]+|null|true|false)\s*,?')
OBJ = re.compile(r"\{[^{}]*\}")


def value(raw):
    raw = raw.strip()
    if raw.startswith('"'):
        return json.loads(raw)
    if raw == "null":
        return None
    if raw in ("true", "false"):
        return raw == "true"
    try:
        return float(raw) if "." in raw else int(raw)
    except ValueError:
        return None


def build():
    text = SRC.read_text(encoding="utf-8")
    text = re.sub(r"^\s*//.*$", "", text, flags=re.M)              # drop comment lines
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end < 0:
        sys.exit("no array found in " + SRC.name)
    out = []
    for block in OBJ.findall(text[start:end]):
        row = {k: value(v) for k, v in FIELD.findall(block)}
        row = {k: row.get(k) for k in ("id", "name", "city", "rating", "reviewCount", "phone", "whatsappNumber")}
        if row["id"] and row["name"]:
            out.append(row)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(out)} halls -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    build()

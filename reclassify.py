"""Re-tag sections in an existing places.json using classify.py.

The crawler's `group` field records *which search query found a row*, not what the business is, so
venues picked up by a marriage-hall search carried the venue tag into unrelated cards (a "Dhol
Party" showed up under Marquee / Venue, a steel-workshop under DJ / Sound). This rewrites
`sections` from each vendor's own name + Google category, then regenerates places_sorted.xlsx.

Idempotent: re-running it produces the same file. Run from the project root:
    python reclassify.py [--dry]
"""
import json, sys, importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("classify", ROOT / "classify.py")
cl = importlib.util.module_from_spec(spec); spec.loader.exec_module(cl)

PLACES = ROOT / "places.json"


def main():
    dry = "--dry" in sys.argv
    rows = json.loads(PLACES.read_text(encoding="utf-8"))

    moved, multi, tally = 0, 0, {c: 0 for c in cl.SECTIONS}
    for r in rows:
        old = list(r.get("sections") or [])
        new = cl.classify(r.get("name"), r.get("category") or "", old)
        if new != old:
            moved += 1
        if len(new) > 1:
            multi += 1
        for s in new:
            tally[s] = tally.get(s, 0) + 1
        if not dry:
            r["sections"] = new

    print(f"rows {len(rows)}  re-tagged {moved}  multi-section {multi}")
    for code, label in cl.SECTIONS.items():
        print(f"  {label:18s} {tally.get(code, 0):5d}")

    if dry:
        print("--dry: places.json left untouched")
        return

    tmp = PLACES.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(PLACES)
    print(f"wrote {PLACES.name}")

    # keep the spreadsheet in step with the JSON (same columns as sort_places.py)
    try:
        from openpyxl import Workbook
    except ImportError:
        print("openpyxl missing - skipped places_sorted.xlsx")
        return
    wb = Workbook(); ws = wb.active; ws.title = "Sorted"
    ws.append(["City", "Area", "Section", "Name", "Rating", "Reviews", "Rank score",
               "Phone", "Address", "Website", "Maps"])
    for r in sorted(rows, key=lambda x: (x["city"], x["area"], x["sections"][0], -x["score"])):
        ws.append([r["city"], r["area"], cl.SECTIONS[r["sections"][0]], r["name"], r["rating"],
                   r["reviews"], r["score"], r["phone"], r["address"], r["website"], r["maps_url"]])
    ws.freeze_panes = "A2"; ws.auto_filter.ref = ws.dimensions
    out = ROOT / "places_sorted.xlsx"
    wb.save(out)
    print(f"wrote {out.name}")


main()

#!/usr/bin/env python3
"""Fill the FORMTEXT fields of the CGN NC license docx (signature stays empty — sign personally).

The 8 FORMTEXT fields, in document order:
  1 Naam Licentienemer   2 Woonachtig te   3 Organisatie   4 Datum
  5 Bijlage 2: omschrijving eigen onderzoek
  6 Postadres            7 Telefoonnummer  8 E-mailadres

Usage:
  python3 scripts/fill_cgn_license.py --values values.json [--in <docx>] [--out <docx>]
values.json: {"naam": ..., "woonplaats": ..., "organisatie": ..., "datum": ...,
              "onderzoek": ..., "postadres": ..., "telefoon": ..., "email": ...}
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORDER = ["naam", "woonplaats", "organisatie", "datum", "onderzoek", "postadres", "telefoon", "email"]


def fill(xml: str, values: list[str]) -> str:
    """A FORMTEXT field: fldChar begin ... instrText FORMTEXT ... fldChar separate
    ... <display runs with placeholder w:t> ... fldChar end.
    We rewrite the CONTENT of the existing placeholder <w:t> runs (first gets the
    value, the rest are blanked) so the run/field structure stays untouched & valid."""
    parts = re.split(r'(<w:fldChar w:fldCharType="(?:begin|separate|end)"/>)', xml)
    out, vi = [], 0
    collecting = None  # display-region buffer for the current FORMTEXT field
    for i, part in enumerate(parts):
        if part == '<w:fldChar w:fldCharType="separate"/>':
            out.append(part)
            back = "".join(parts[max(0, i - 2):i])
            if "FORMTEXT" in back:
                collecting = []
        elif part == '<w:fldChar w:fldCharType="end"/>':
            if collecting is not None:
                region = "".join(collecting)
                val = values[vi] if vi < len(values) else ""
                esc = val.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                esc = esc.replace("\n", '</w:t></w:r><w:r><w:br/><w:t xml:space="preserve">')
                first = [True]

                def repl(m, esc=esc, first=first):
                    if first[0]:
                        first[0] = False
                        return f'<w:t xml:space="preserve">{esc}</w:t>'
                    return '<w:t xml:space="preserve"></w:t>'

                new_region, n = re.subn(r"<w:t[^>]*>.*?</w:t>", repl, region, flags=re.S)
                if n == 0:
                    raise SystemExit(f"field {vi+1}: no placeholder text run found — structure changed?")
                out.append(new_region)
                vi += 1
                collecting = None
            out.append(part)
        else:
            if collecting is not None:
                collecting.append(part)
            else:
                out.append(part)
    if vi != len(values):
        raise SystemExit(f"expected to fill {len(values)} fields, filled {vi} — document structure changed?")
    return "".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--values", required=True)
    ap.add_argument("--infile", default=str(ROOT / "data/cgn/order/Licentie-NC_CGN.docx"))
    ap.add_argument("--out", default=str(ROOT / "data/cgn/order/Licentie-NC_CGN_INGEVULD.docx"))
    args = ap.parse_args()
    vals = json.loads(Path(args.values).read_text())
    values = [vals[k] for k in ORDER]

    shutil.copy(args.infile, args.out)
    with zipfile.ZipFile(args.infile) as zin:
        items = {n: zin.read(n) for n in zin.namelist()}
    xml = items["word/document.xml"].decode("utf-8")
    items["word/document.xml"] = fill(xml, values).encode("utf-8")
    with zipfile.ZipFile(args.out, "w", zipfile.ZIP_DEFLATED) as zout:
        for n, data in items.items():
            zout.writestr(n, data)
    print("filled ->", args.out)


if __name__ == "__main__":
    main()

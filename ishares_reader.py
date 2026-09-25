"""
ishares_reader.py — lecture des classeurs « Data Download » d'iShares.

Sert à l'AUDIT : on télécharge à la main quelques classeurs iShares (une fois
par an suffit) et fetch_data.py --audit DOSSIER compare leurs rendements
totaux (NAV officielle + distributions) avec ceux de yfinance.

Formats reconnus : SpreadsheetML 2003 (UTF-8 ou UTF-16), tableau HTML
déguisé en .xls, vrai .xls binaire (nécessite xlrd).
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import pandas as pd
from lxml import etree

SPLIT_JUMP = 0.25          # variation quotidienne au-delà → split suspecté
SPLIT_FACTORS = [2, 3, 4, 5, 8, 10, 20]
SPLIT_TOL = 0.03


def _local(tag) -> str:
    return etree.QName(tag).localname if isinstance(tag, str) else ""


def _attr(el, name: str):
    for k, v in el.attrib.items():
        if _local(k) == name:
            return v
    return None


OLE_MAGIC = b"\xd0\xcf\x11\xe0"  # vrai .xls binaire (format BIFF)


def _to_text(raw: bytes) -> str:
    """Décode en gérant UTF-8 (avec ou sans BOM) et UTF-16."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    if len(raw) > 4 and raw[1:2] == b"\x00" and raw[3:4] == b"\x00":
        return raw.decode("utf-16-le", errors="replace")
    if len(raw) > 4 and raw[0:1] == b"\x00" and raw[2:3] == b"\x00":
        return raw.decode("utf-16-be", errors="replace")
    return raw.decode("utf-8-sig", errors="replace")


def _read_html_tables(text: str) -> dict[str, list[list]]:
    """Tableaux HTML lus tels quels (texte brut des cellules, sans conversion)."""
    from lxml import html as lhtml
    doc = lhtml.fromstring(text)
    out = {}
    for i, table in enumerate(doc.iter("table")):
        rows = [[(c.text_content() or "").strip() or None for c in tr if c.tag in ("td", "th")]
                for tr in table.iter("tr")]
        out[f"Table{i+1}"] = rows
    return out


def _read_binary_xls(path: Path) -> dict[str, list[list]]:
    try:
        book = pd.read_excel(path, sheet_name=None, header=None, dtype=str)
    except ImportError as e:
        raise ValueError("fichier .xls binaire : installe xlrd (pip install xlrd)") from e
    return {name: df.where(df.notna(), None).values.tolist() for name, df in book.items()}


def read_workbook(path: Path) -> dict[str, list[list]]:
    raw = path.read_bytes()
    if raw.startswith(OLE_MAGIC):
        return _read_binary_xls(path)
    text = _to_text(raw).lstrip()
    if "<table" in text[:20000].lower() and "workbook" not in text[:20000].lower():
        return _read_html_tables(text)
    # SpreadsheetML : on retire la déclaration XML (son encodage ne correspond plus)
    text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text)
    parser = etree.XMLParser(recover=True, huge_tree=True)
    root = etree.fromstring(text.encode("utf-8"), parser)
    if root is None:
        raise ValueError("fichier illisible (ni SpreadsheetML, ni HTML, ni .xls binaire) — "
                         f"début du fichier : {text[:120]!r}")
    sheets: dict[str, list[list]] = {}
    for ws in root.iter():
        if _local(ws.tag) != "Worksheet":
            continue
        rows = []
        for row in ws.iter():
            if _local(row.tag) != "Row":
                continue
            cells: list = []
            for cell in row:
                if _local(cell.tag) != "Cell":
                    continue
                idx = _attr(cell, "Index")
                if idx:
                    while len(cells) < int(idx) - 1:
                        cells.append(None)
                data = next((c for c in cell if _local(c.tag) == "Data"), None)
                cells.append("".join(data.itertext()).strip() if data is not None else None)
            rows.append(cells)
        sheets[_attr(ws, "Name") or f"Sheet{len(sheets)+1}"] = rows
    return sheets


def _num(x):
    if x is None:
        return math.nan
    s = str(x).replace("$", "").replace(",", "").replace(" ", "").strip()
    if s in ("", "-", "--", "N/A", "n/a", "NA"):
        return math.nan
    try:
        return float(s)
    except ValueError:
        return math.nan


def extract_history(sheets: dict) -> pd.DataFrame:
    """Renvoie un DataFrame (date, nav, div) trié par date croissante."""
    def find_header(rows):
        for i, r in enumerate(rows[:50]):
            low = [str(c or "").lower() for c in r]
            if any("as of" in c for c in low) and any("nav" in c for c in low):
                return i
        return None

    # onglet « Historical » en priorité, sinon le premier onglet qui a l'en-tête attendu
    order = sorted(sheets, key=lambda n: "historical" not in n.lower())
    rows, header_i = None, None
    for n in order:
        h = find_header(sheets[n])
        if h is not None:
            rows, header_i = sheets[n], h
            break
    if rows is None:
        raise ValueError(f"en-tête « As Of / NAV » introuvable (onglets : {list(sheets)})")

    hdr = [str(c or "").lower() for c in rows[header_i]]
    c_date = next(i for i, c in enumerate(hdr) if "as of" in c)
    c_nav = next(i for i, c in enumerate(hdr) if "nav" in c)
    c_div = next((i for i, c in enumerate(hdr)
                  if "dividend" in c or "distribution" in c), None)

    recs = []
    for r in rows[header_i + 1:]:
        if len(r) <= max(c_date, c_nav) or not r[c_date]:
            continue
        recs.append((r[c_date], _num(r[c_nav]),
                     _num(r[c_div]) if c_div is not None and c_div < len(r) else math.nan))
    df = pd.DataFrame(recs, columns=["date", "nav", "div"])
    d = pd.to_datetime(df["date"], format="%b %d, %Y", errors="coerce")
    d = d.fillna(pd.to_datetime(df["date"], errors="coerce"))
    df["date"] = d
    df = df.dropna(subset=["date", "nav"])
    df = df[df["nav"] > 0]
    df["div"] = df["div"].fillna(0.0)
    # une ligne par jour ; si doublon, on garde la dernière
    df = df.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    if len(df) < 30:
        raise ValueError(f"historique trop court ({len(df)} lignes)")
    return df


def daily_total_returns(df: pd.DataFrame) -> tuple[pd.Series, list[str]]:
    """r_t = (NAV_t + D_t) / NAV_{t-1} - 1, avec neutralisation des splits."""
    nav, div = df["nav"].to_numpy(), df["div"].to_numpy()
    notes, r = [], [math.nan]
    for t in range(1, len(df)):
        ratio = (nav[t] + div[t]) / nav[t - 1]
        if abs(ratio - 1) > SPLIT_JUMP:
            fixed = None
            for n in SPLIT_FACTORS:
                if abs(ratio * n - 1) < SPLIT_TOL:       # split n-pour-1
                    fixed = ratio * n
                    notes.append(f"split {n}:1 neutralisé le {df['date'][t]:%Y-%m-%d}")
                elif abs(ratio / n - 1) < SPLIT_TOL:     # regroupement 1-pour-n
                    fixed = ratio / n
                    notes.append(f"regroupement 1:{n} neutralisé le {df['date'][t]:%Y-%m-%d}")
                if fixed is not None:
                    break
            if fixed is not None:
                ratio = fixed
        r.append(ratio - 1)
    return pd.Series(r, index=df["date"]), notes


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower().replace("&", ""))


def find_local_file(folder: Path, ticker: str, cfg: dict) -> Path | None:
    """Accepte IVV_fund.xls comme iShares-Core-SP-500-ETF_fund.xls."""
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".xls", ".xlsx", ".xml"))
    for p in files:  # 1) nom qui commence par le ticker
        if re.match(rf"{ticker}([_\-. ]|$)", p.stem, re.I):
            return p
    targets = {t.removesuffix("etf") for t in (_norm(cfg.get("name", "")), _norm(cfg.get("slug", ""))) if t}
    for p in files:  # 2) nom du fonds ou slug (ce qu'iShares met dans le nom du fichier)
        stem = _norm(re.sub(r"_fund$", "", p.stem, flags=re.I)).removesuffix("etf")
        if stem in targets:
            return p
    return None

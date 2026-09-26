#!/usr/bin/env python3
"""
build_site.py — génère les vraies pages HTML du site (une par adresse).

À partir de templates/app.html (le site interactif) et des données
(site/strategies.json, fiches.json, ucits.json, content/methode.html), écrit :

  site/index.html                     accueil (tableau comparatif)
  site/strategies/<id>/index.html     une page par stratégie
  site/equivalents-ucits/index.html   table des équivalents UCITS
  site/methode/index.html             méthode et limites
  site/404.html, site/sitemap.xml, site/robots.txt

Chaque page contient son contenu en HTML (lisible par les moteurs de recherche
et les aperçus de liens), son titre, sa description et ses balises Open Graph.
Le JavaScript prend ensuite le relais pour les graphiques interactifs.

Appelé automatiquement à la fin de run_backtests.py. Seul : python3 build_site.py
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "site"
TEMPLATE = ROOT / "templates" / "app.html"
CONFIG = ROOT / "site_config.json"

MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
MOIS_LONG = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
             "octobre", "novembre", "décembre"]
NBSP = " "
REF_NAMES = {"acwi": "Actions mondiales", "spy": "S&P 500"}
MATCH = {"meme": "même indice", "proche": "proche", "aucun": "aucun"}


# --------------------------------------------------------------------------
# Mise en forme (identique au site)
# --------------------------------------------------------------------------
def e(x) -> str:
    return html.escape(str(x), quote=True)


def m_label(p: str | None) -> str:
    if not p:
        return "—"
    y, m = p.split("-")[:2]
    return f"{MOIS[int(m) - 1]} {y}"


def m_long(p: str) -> str:
    y, m = p.split("-")[:2]
    return f"{MOIS_LONG[int(m) - 1]} {y}"


def next_month(p: str) -> str:
    y, m = map(int, p.split("-")[:2])
    return f"{y + (m == 12)}-{(m % 12) + 1:02d}"


def num(v, d=1) -> str:
    return f"{v:,.{d}f}".replace(",", " ").replace(".", ",").replace(" ", NBSP)


def pct(v, d=1, sign=False) -> str:
    if v is None:
        return "—"
    s = num(v * 100, d)
    return ("+" if sign and v > 0 else "") + s + NBSP + "%"


def dec(v, d=2) -> str:
    return "—" if v is None else num(v, d)


def uw(st) -> str:
    n = st.get("underwater_months")
    return "—" if n is None else f"{n}{'+' if st.get('underwater_ongoing') else ''}{NBSP}mois"


def weight_text(w: float) -> str:
    return num(w * 100, 0 if abs(w * 100 - round(w * 100)) < 1e-9 else 1) + NBSP + "%"


# --------------------------------------------------------------------------
# Gabarit
# --------------------------------------------------------------------------
def split_template(tpl: str) -> tuple[str, str]:
    """Retire les balises d'en-tête du prototype et sépare <head> / <body>."""
    for pat in (r'<meta charset="utf-8">\s*', r'<meta name="viewport"[^>]*>\s*',
                r"<title>.*?</title>\s*", r'<meta name="description"[^>]*>\s*'):
        tpl = re.sub(pat, "", tpl, count=1, flags=re.S)
    i = tpl.index('<div class="wrap">')
    return tpl[:i], tpl[i:]


def page(head_tpl: str, body_tpl: str, *, cfg: dict, path: str, title: str, desc: str,
         content: str, nav: str, stamp: str, og_type="website", noindex=False, jsonld=None) -> str:
    url = cfg["site_url"].rstrip("/") + "/" + path
    meta = [
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">',
        f"<title>{e(title)}</title>",
        f'<meta name="description" content="{e(desc)}">',
        f'<link rel="canonical" href="{e(url)}">',
        '<meta property="og:site_name" content="ETF Strategy Lab">',
        '<meta property="og:locale" content="fr_FR">',
        f'<meta property="og:type" content="{og_type}">',
        f'<meta property="og:title" content="{e(title)}">',
        f'<meta property="og:description" content="{e(desc)}">',
        f'<meta property="og:url" content="{e(url)}">',
        '<meta name="twitter:card" content="summary">',
    ]
    if noindex:
        meta.append('<meta name="robots" content="noindex">')
    if jsonld:
        meta.append('<script type="application/ld+json">'
                    + json.dumps(jsonld, ensure_ascii=False).replace("</", "<\\/") + "</script>")
    body = body_tpl
    # liens de navigation réels
    body = body.replace('class="brand" href="#"', 'class="brand" href="/"')
    body = body.replace('<a href="#" data-nav="">', '<a href="/" data-nav="">')
    body = body.replace('href="#ucits"', 'href="/equivalents-ucits/"').replace('href="#methode"', 'href="/methode/"')
    body = body.replace(f'data-nav="{nav}">', f'data-nav="{nav}" aria-current="page">', 1)
    body = body.replace('<span class="stamp" id="stamp">Chargement…</span>',
                        f'<span class="stamp" id="stamp">{e(stamp)}</span>')
    body = body.replace('<main id="app" aria-live="polite"></main>',
                        f'<main id="app" aria-live="polite">{content}</main>')
    body = body.replace("<script>", '<script>window.ESL_BASE = "/";</script>\n<script>', 1)
    return ("<!doctype html>\n<html lang=\"fr\">\n<head>\n" + "\n".join(meta) + "\n"
            + head_tpl.strip() + "\n</head>\n<body>\n" + body.strip() + "\n</body>\n</html>\n")


# --------------------------------------------------------------------------
# Contenus
# --------------------------------------------------------------------------
def intro_sentence(data, ref) -> str:
    rs = ref["stats_common"]
    strats = [s for s in data["strategies"] if s["id"] not in REF_NAMES]
    n = len(strats)
    better = sum(s["stats_common"]["cagr"] > rs["cagr"] for s in strats)
    sharper = sum((s["stats_common"]["sharpe"] or -9) > rs["sharpe"] for s in strats)
    shallower = sum(s["stats_common"]["max_dd"] > rs["max_dd"] for s in strats)
    name = "les actions mondiales" if ref["id"] == "acwi" else "le S&amp;P 500"
    verb = lambda k: "ont" if k > 1 else "a"
    sh = f"toutes les {n}" if shallower == n else str(shallower)
    sp = "toutes" if sharper == n else str(sharper)
    return (f"Depuis {m_label(data['common_window'][0])}, <b>{better} stratégie{'s' if better > 1 else ''} sur {n}</b> "
            f"{verb(better)} rapporté plus que {name} ({pct(rs['cagr'])} par an). Mais <b>{sh}</b> {verb(shallower)} "
            f"subi une pire baisse moins profonde que ses {pct(rs['max_dd'], 0)}, et <b>{sp}</b> {verb(sharper)} "
            f"mieux rémunéré chaque unité de risque. La vraie question n'est pas seulement combien une stratégie "
            f"rapporte, mais ce qu'elle fait traverser pour y arriver.")


def board_html(data, ref) -> str:
    c0, c1 = data["common_window"]
    rows = sorted(data["strategies"], key=lambda s: -(s["stats_common"]["sharpe"] or -9))
    trs = []
    for s in rows:
        st = s["stats_common"]
        trs.append(
            f'<tr class="{"is-bench" if s["id"] in REF_NAMES else ""}"><td><div class="s-name">'
            f'<a class="s-link" href="/strategies/{s["id"]}/">{e(s["name"])}</a></div>'
            f'<div class="s-meta"><span class="fam">{e(s["family"])}</span></div></td>'
            f'<td class="num">{pct(st["cagr"])}</td><td class="num">{dec(st["sharpe"])}</td>'
            f'<td class="num neg">{pct(st["max_dd"])}</td><td class="num">{uw(st)}</td>'
            f'<td class="num">{pct(st["worst_year"], 1, True)}</td></tr>')
    return f"""
      <section class="intro">
        <h1>Les stratégies ETF connues, testées sur les mêmes données et avec les mêmes règles</h1>
        <p class="key">{intro_sentence(data, ref)}</p>
        <p>Portefeuilles permanents, momentum, suivi de tendance : chaque stratégie est recalculée chaque mois à partir des rendements réels des ETF, frais compris, puis comparée sur la même période. Cliquez sur une stratégie pour ouvrir sa fiche.</p>
        <ul class="method">
          <li>Période commune <b>{m_label(c0)} → {m_label(c1)}</b></li>
          <li>Frais <b>{num(data['cost_per_trade'] * 100, 2)}{NBSP}%</b> par transaction</li>
          <li>Rééquilibrage <b>fin de mois</b></li>
          <li>Devise <b>USD</b></li>
        </ul>
      </section>
      <div class="table-scroll"><table class="board">
        <thead><tr><th scope="col">Stratégie</th><th scope="col">CAGR</th><th scope="col">Sharpe</th>
          <th scope="col">Max DD</th><th scope="col">Récup.</th><th scope="col">Pire année</th></tr></thead>
        <tbody>{''.join(trs)}</tbody></table></div>
      <p class="note-under">Période commune de {m_label(c0)} à {m_label(c1)}, frais inclus. CAGR : rendement annualisé. Sharpe : rendement au-delà des T-bills, divisé par la volatilité. Max DD : pire baisse depuis un sommet. Récup. : plus longue période passée sous un sommet précédent.</p>"""


def rules_for(s) -> list[str]:
    if s.get("rules"):
        return s["rules"]
    w = sorted(s["next_signal"]["weights"].items(), key=lambda kv: -kv[1])
    rb = ("Rééquilibrage une fois par an, fin décembre, pour revenir aux poids cibles."
          if s["rebalance"] == "annual" else "Rééquilibrage chaque fin de mois.")
    return ["Allocation fixe : " + ", ".join(f"{weight_text(v)} {k}" for k, v in w) + ".", rb]


def ucits_item(t, uc) -> str:
    m = uc["map"].get(t)
    if not m:
        return ""
    funds = [uc["_funds"][k] for k in m["funds"]]
    lines = "".join(f'<div class="fmeta">{e(f["name"])} · <span class="isin">{f["isin"]}</span> · '
                    f'frais {num(f["ter"], 2)}{NBSP}%</div>' for f in funds)
    main = " + ".join(f'<b>{e(f["tickers"].split(" (")[0])}</b>' for f in funds) or "<span>—</span>"
    note = f'<div class="unote">{e(m["note"])}</div>' if m.get("note") else ""
    return (f'<div class="ucits-item"><div class="top"><span class="us num">{"Cash" if t == "CASH" else e(t)}</span>'
            f'<span aria-hidden="true">→</span>{main}<span class="match {m["match"]}">{MATCH[m["match"]]}</span></div>'
            f'{lines}{note}</div>')


def sheet_html(s, data, fiches, uc, ref) -> str:
    st, sf = s["stats_common"], s["stats_full"]
    rst = ref["stats_common"]
    rname = REF_NAMES[ref["id"]]
    f = fiches.get(s["id"])
    cmp = lambda v: "" if s["id"] == ref["id"] else f'<span class="cmp">{e(rname)} : <span class="num">{v}</span></span>'
    ess = ""
    if f:
        ess = (f'<section class="panel"><h2>L\'essentiel</h2><div class="essentials"><p>{e(f["idee"])}</p>'
               f'<h3>Points forts</h3><ul>{"".join(f"<li>{e(x)}</li>" for x in f["forces"])}</ul>'
               f'<h3>Points faibles</h3><ul>{"".join(f"<li>{e(x)}</li>" for x in f["faiblesses"])}</ul>'
               + (f'<h3>À savoir</h3><p>{e(f["a_savoir"])}</p>' if f.get("a_savoir") else "") + "</div></section>")
    nm = s["next_signal"]["for_month"]
    sig = "".join(
        f'<div class="alloc-row"><span class="tk">{"Cash" if k == "CASH" else e(k)}</span>'
        f'<span class="bar"><i style="width:{v * 100:.1f}%"></i></span><span class="pc num">{weight_text(v)}</span>'
        f'<span class="nm">{"T-bills (BIL)" if k == "CASH" else e(data["etf_names"].get(k, ""))}</span></div>'
        for k, v in sorted(s["next_signal"]["weights"].items(), key=lambda kv: -kv[1]))
    extra = ""
    if s.get("variant_note"):
        extra += f'<div class="callout">{e(s["variant_note"])}</div>'
    if s.get("published"):
        extra += f'<div class="callout"><b>Publiée en {m_long(s["published"])}.</b></div>'
    assets = list(dict.fromkeys(s["assets"] + (["CASH"] if s.get("uses_cash") or "CASH" in s["next_signal"]["weights"] else [])))
    ucits = "".join(ucits_item(a, uc) for a in assets) if uc else ""
    metrics = [
        ("Début", lambda x: m_label(x["start"])), ("CAGR", lambda x: pct(x["cagr"])),
        ("Volatilité", lambda x: pct(x["vol"])), ("Sharpe", lambda x: dec(x["sharpe"])),
        ("Max drawdown", lambda x: pct(x["max_dd"])), ("Plus longue période sous l'eau", uw),
        ("Meilleure année", lambda x: pct(x["best_year"], 1, True)), ("Pire année", lambda x: pct(x["worst_year"], 1, True)),
        ("Pire 5 ans (annualisé)", lambda x: pct(x["roll5_min"], 1, True)),
        ("Pire 10 ans (annualisé)", lambda x: pct(x["roll10_min"], 1, True)),
    ]
    mt = "".join(f'<tr><td>{l}</td><td class="num">{fn(st)}</td><td class="num">{fn(sf)}</td></tr>' for l, fn in metrics)
    return f"""
      <a class="back" href="/">← Toutes les stratégies</a>
      <section class="sheet-head">
        <div class="byline"><span class="fam">{e(s['family'])}</span><span>{e(s.get('author', ''))}</span></div>
        <h1>{e(s['name'])}</h1>
        <p class="lede">{e(s.get('note', ''))}</p>
      </section>
      <div class="tiles">
        <div class="tile"><span class="k">CAGR</span><span class="v">{pct(st['cagr'])}</span>{cmp(pct(rst['cagr']))}</div>
        <div class="tile"><span class="k">Temps de récupération</span><span class="v">{uw(st)}</span>{cmp(uw(rst))}</div>
        <div class="tile"><span class="k">Max drawdown</span><span class="v neg">{pct(st['max_dd'])}</span>{cmp(pct(rst['max_dd']))}</div>
        <div class="tile"><span class="k">Pire année</span><span class="v">{pct(st['worst_year'], 1, True)}</span>{cmp(pct(rst['worst_year'], 1, True))}</div>
      </div>
      <div class="grid-2"><div class="stack">
        {ess}
        <section class="panel"><h2>Règles</h2><ol class="rules">{''.join(f'<li>{e(r)}</li>' for r in rules_for(s))}</ol>{extra}</section>
      </div><div class="stack">
        <section class="panel"><h2>Signal pour {m_long(nm)}</h2><p class="sub">Calculé sur la clôture de fin {m_long(data['data_end'])}.</p><div class="alloc">{sig}</div></section>
        {f'<section class="panel"><h2>Avec des ETF européens</h2><div class="ucits-list">{ucits}</div></section>' if ucits else ''}
        <section class="panel"><h2>Toutes les mesures</h2><table class="metrics"><thead><tr><th scope="col"></th><th scope="col">Commune</th><th scope="col">Complet</th></tr></thead><tbody>{mt}</tbody></table></section>
      </div></div>"""


def ucits_html(data, uc) -> str:
    order = [t for t in ["ACWI", "SPY", "IVV", "VTI", "QQQ", "IWM", "IWN", "EFA", "VEA", "ACWX", "VGK", "EWJ", "SCZ",
                         "EEM", "VWO", "VNQ", "RWX", "REM", "GLD", "DBC", "GSG", "TLT", "IEF", "SHY", "SHV", "BIL",
                         "TIP", "AGG", "BND", "LQD", "HYG", "BWX", "XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU",
                         "XLV", "XLY"] if t in uc["map"]]
    rows = []
    for t in order:
        m = uc["map"][t]
        funds = "".join(
            f'<div class="fund"><div class="fname">{e(f["name"])}</div><div class="fmeta">'
            f'<span class="part"><span class="lab">ISIN</span><span class="isin">{f["isin"]}</span></span><span class="sep"> · </span>'
            f'<span class="part"><span class="lab">Cotations</span>{e(f["tickers"])}</span><span class="sep"> · </span>'
            f'<span class="part"><span class="lab">Frais</span><span class="num">{num(f["ter"], 2)}{NBSP}%</span> par an</span></div></div>'
            for f in (uc["_funds"][k] for k in m["funds"])) or "—"
        note = f'<div class="unote">{e(m["note"])}</div>' if m.get("note") else ""
        rows.append(f'<tr><td><span class="us">{t}</span><div class="fmeta">{e(data["etf_names"].get(t, ""))}</div></td>'
                    f'<td><span class="match {m["match"]}">{MATCH[m["match"]]}</span></td><td>{funds}{note}</td></tr>')
    return f"""
      <section class="doc">
        <h1>Équivalents UCITS des ETF américains</h1>
        <p class="lede">Depuis 2018, la réglementation européenne (PRIIPs) empêche les particuliers d'acheter la plupart des ETF américains. Les stratégies de ce site restent applicables avec des ETF domiciliés en Europe, dits UCITS. Cette table donne, pour chaque ETF utilisé, l'équivalent le plus proche.</p>
        <p><span class="match meme">même indice</span> même indice ou quasi identique · <span class="match proche">proche</span> même classe d'actifs, indice différent · <span class="match aucun">aucun</span> pas d'équivalent satisfaisant</p>
      </section>
      <div class="table-scroll" style="margin-top:18px"><table class="ucits">
        <thead><tr><th scope="col">ETF US</th><th scope="col">Correspondance</th><th scope="col">Équivalent UCITS</th></tr></thead>
        <tbody>{''.join(rows)}</tbody></table></div>
      <p class="note-under">ISIN, tickers et frais vérifiés sur justETF. Plusieurs cotations existent pour chaque fonds (devise, bourse) : vérifiez celle proposée par votre courtier. Cette table n'est pas une recommandation d'achat.</p>"""


def method_html(data) -> str:
    frag = (SITE / "content" / "methode.html").read_text(encoding="utf-8")
    c0, c1 = data["common_window"]
    return (frag.replace("{{C0}}", m_label(c0)).replace("{{C1}}", m_label(c1))
            .replace("{{COST}}", num(data["cost_per_trade"] * 100, 2)))


def clip(t: str, n=160) -> str:
    return t if len(t) <= n else t[: n - 1].rsplit(" ", 1)[0].rstrip(" .,;:") + "…"


# --------------------------------------------------------------------------
# Construction
# --------------------------------------------------------------------------
def build(root: Path = ROOT) -> list[str]:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {
        "site_url": "https://etf-strategy-lab.netlify.app"}
    data = json.loads((SITE / "strategies.json").read_text(encoding="utf-8"))
    fiches = json.loads((SITE / "fiches.json").read_text(encoding="utf-8")) if (SITE / "fiches.json").exists() else {}
    uc = json.loads((SITE / "ucits.json").read_text(encoding="utf-8")) if (SITE / "ucits.json").exists() else None
    head_tpl, body_tpl = split_template(TEMPLATE.read_text(encoding="utf-8"))
    by_id = {s["id"]: s for s in data["strategies"]}
    ref = by_id.get("acwi") or by_id["spy"]
    c0 = data["common_window"][0]
    stamp = f"Données à fin {m_long(data['data_end'])} · {len(data['strategies'])} stratégies"
    base_url = cfg["site_url"].rstrip("/")
    written = []

    def write(rel: str, text: str):
        out = SITE / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        written.append(rel)

    common = dict(cfg=cfg, stamp=stamp)
    n = len([s for s in data["strategies"] if s["id"] not in REF_NAMES])
    write("index.html", page(head_tpl, body_tpl, path="", nav="", content=board_html(data, ref),
                             title="ETF Strategy Lab : les stratégies ETF backtestées et comparées",
                             desc=clip(f"{n} stratégies d'investissement en ETF (Permanent Portfolio, Dual Momentum, "
                                       f"stratégies de Keller…) testées depuis {m_label(c0)} avec les mêmes données : "
                                       "rendement, pire baisse, signal du mois."),
                             jsonld={"@context": "https://schema.org", "@type": "WebSite", "name": "ETF Strategy Lab",
                                     "url": base_url + "/", "inLanguage": "fr"}, **common))
    for s in data["strategies"]:
        st = s["stats_common"]
        month = m_long(s["next_signal"]["for_month"])
        desc = (f"{s.get('note', s['name'])}. Depuis {m_label(st['start'])} : {pct(st['cagr'])} par an, "
                f"pire baisse {pct(st['max_dd'])}.")
        tail = " Règles, signal du mois, équivalents UCITS."
        desc = clip(desc + tail if len(desc + tail) <= 160 else desc)
        write(f"strategies/{s['id']}/index.html",
              page(head_tpl, body_tpl, path=f"strategies/{s['id']}/", nav="", og_type="article",
                   content=sheet_html(s, data, fiches, uc, ref),
                   title=f"{s['name']} : backtest, règles et signal du mois | ETF Strategy Lab", desc=desc,
                   jsonld={"@context": "https://schema.org", "@type": "WebPage", "name": s["name"],
                           "description": desc, "inLanguage": "fr",
                           "isPartOf": {"@type": "WebSite", "name": "ETF Strategy Lab", "url": base_url + "/"}},
                   **common))
    if uc:
        write("equivalents-ucits/index.html",
              page(head_tpl, body_tpl, path="equivalents-ucits/", nav="ucits", content=ucits_html(data, uc),
                   title="Équivalents UCITS des ETF américains (ISIN, tickers, frais) | ETF Strategy Lab",
                   desc="Pour chaque ETF américain (SPY, TLT, GLD, QQQ…), l'équivalent UCITS accessible en Europe : "
                        "ISIN, cotations, frais et niveau de correspondance.", **common))
    write("methode/index.html",
          page(head_tpl, body_tpl, path="methode/", nav="methode", content=method_html(data),
               title="Méthode et limites des backtests | ETF Strategy Lab",
               desc="Données, conventions de calcul, période commune, mesures et limites des backtests "
                    "d'ETF Strategy Lab.", **common))
    write("404.html",
          page(head_tpl, body_tpl, path="404.html", nav="", noindex=True,
               content='<section class="doc"><h1>Page introuvable</h1><p class="lede">Cette adresse n\'existe pas '
                       '(ou plus). <a href="/">Voir toutes les stratégies</a>.</p></section>',
               title="Page introuvable | ETF Strategy Lab", desc="Page introuvable.", **common).replace(
                   '<script>window.ESL_BASE = "/";</script>', '<script>window.ESL_BASE = "/"; window.ESL_404 = true;</script>'))
    today = dt.date.today().isoformat()
    urls = ["", "equivalents-ucits/", "methode/"] + [f"strategies/{s['id']}/" for s in data["strategies"]]
    write("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
          + "".join(f"  <url><loc>{base_url}/{u}</loc><lastmod>{today}</lastmod></url>\n" for u in urls) + "</urlset>\n")
    write("robots.txt", f"User-agent: *\nAllow: /\n\nSitemap: {base_url}/sitemap.xml\n")
    return written


if __name__ == "__main__":
    files = build()
    print(f"{len(files)} fichiers générés dans site/ ({sum(f.endswith('index.html') for f in files)} pages)")

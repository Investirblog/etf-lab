# Labo ETF : pipeline de données

Construit une table de **rendements totaux mensuels** (dividendes réinvestis) pour les ~40 ETF US nécessaires aux stratégies du site. C'est sur cette table que tournent les backtests.

- **Source principale : yfinance.** Cours ajustés des dividendes et des splits, soit l'équivalent d'un rendement total.
- **Contrôle : classeurs iShares** (NAV officielle), téléchargés à la main une fois par an, puis comparés automatiquement.

## Lancement

```bash
pip install -r requirements.txt
python3 fetch_data.py                   # tout l'univers (~2 min)
python3 fetch_data.py --only SPY TLT    # sous-ensemble (les autres colonnes sont conservées)
python3 fetch_data.py --audit manuel    # + audit avec les classeurs iShares du dossier manuel/
python3 fetch_data.py --offline         # reconstruit depuis le cache, sans réseau
```

Ensuite, ouvre `data/quality_report.md`.

## Fichiers produits (`data/`)

| Fichier | Contenu |
|---|---|
| `monthly_returns.csv` | 1 ligne par mois (`2024-05`), 1 colonne par ETF, rendements en décimal |
| `monthly_tr_index.csv` | même chose en indice base 100 (pour les graphiques) |
| `daily/<TICKER>.csv` | cours ajustés quotidiens, sert aussi de cache si Yahoo ne répond pas |
| `meta.json` | couverture de chaque ETF, fenêtre commune |
| `quality_report.md` | audit iShares + alertes par ETF |

## Contrôles qualité

- **Données** : mois manquants, rendement mensuel au-delà de ±25 %, variation quotidienne au-delà de ±20 % (mauvaise cotation), trous de cotation, mois incomplet ou en retard.
- **Révisions** : Yahoo corrige parfois l'historique (un dividende rectifié, par exemple). Chaque mois déjà publié qui change de plus de 0,25 point est signalé.
- **Audit iShares** : écart mensuel moyen et écart de CAGR entre yfinance et la NAV officielle. Le résultat est ✅ si l'écart mensuel moyen reste sous 0,30 % et l'écart de CAGR sous 0,20 %/an.

## Audit iShares (1 fois par an)

1. Sur la page iShares d'un fonds, clique sur « Data Download ».
2. Mets le fichier dans `manuel/`. Le nom d'origine (`iShares-Core-SP-500-ETF_fund.xls`) est reconnu ; sinon, renomme-le en `TICKER_fund.xls`.
3. Lance `python3 fetch_data.py --audit manuel`.

Il suffit de 4 ou 5 fonds représentatifs : IVV, TLT, EFA, HYG, TIP.

## Automatisation

`.github/workflows/update-data.yml` tourne les 2, 3 et 4 de chaque mois et committe `data/` si quelque chose a changé. En cas d'erreur, le workflow échoue (GitHub t'envoie un e-mail), mais les ETF réussis sont sauvegardés et ceux en échec gardent leurs données en cache.

## Backtests

```bash
python3 run_backtests.py              # frais de 0,10 % par transaction
python3 run_backtests.py --cost 0     # sans frais
```

- `engine.py` : le moteur commun. À la fin de chaque mois, la stratégie reçoit l'historique et renvoie les poids du mois suivant ; le moteur gère la dérive des poids, le rebalancement et les frais.
- `metrics.py` : CAGR, volatilité, Sharpe, Sortino, max drawdown (dates et récupération), Ulcer, meilleure et pire année, pire CAGR sur 5 et 10 ans glissants.
- `strategies_static.py` : les portefeuilles fixes. Chaque nouvelle famille aura son fichier.
- `results/` : `summary_common.csv` (fenêtre commune), `summary_full.csv` (historique complet) et `strategies.json` (tout ce qu'il faut au site).

La vue en euros utilise le cours EUR/USD (colonne `EURUSD` : FRED DEXUSEU, complété par Yahoo `EURUSD=X` pour les mois récents) et le taux de dépôt de la BCE (colonne `ECBDEP`, FRED ECBDFR, plancher 0 %), qui rémunère la part cash en euros, téléchargés par `fetch_data.py`.

Le cash (`CASH`) correspond à BIL ; avant son lancement (2007), au taux des T-bills à 3 mois de la Fed (série FRED TB3MS, colonne `TBILL`, téléchargée par `fetch_data.py`). Les références du site sont les actions mondiales (ACWI) et le S&P 500 (SPY).

## Site

Le site interactif est dans `templates/app.html`. À chaque `run_backtests.py`, le générateur `build_site.py` produit dans `site/` une vraie page HTML par adresse :

- `/` (accueil), `/strategies/<id>/` (une page par stratégie, avec l'historique des signaux), `/signaux/` (signaux du mois, ce qui change), une page par famille (`/momentum/`, `/strategies-keller/`…), `/comparer/` (comparateur interactif) et les pages « X ou Y ? » (`/comparer/gem-ou-adm/`…), `/equivalents-ucits/`, `/methode/`, `/mentions-legales/`, `404.html` ;
- `og/*.png` : une image d'aperçu par page pour les réseaux sociaux (`og_images.py`, via matplotlib) ;
- `sitemap.xml` et `robots.txt`.

Chaque page contient son texte en HTML, avec titre, description, lien canonique et balises Open Graph : Google et les aperçus de liens (X, Facebook, WhatsApp) la lisent sans exécuter de JavaScript. Le script prend ensuite le relais pour les graphiques. Les anciens liens (`/#gem`) redirigent vers les nouvelles adresses.

Fichiers à modifier à la main :
- `site/fiches.json` : les textes des fiches ;
- `site/ucits.json` : les équivalents UCITS ;
- `site/content/methode.html` : la page Méthode ;
- `site/content/familles.json` : les textes des pages par famille ;
- `site/content/comparaisons.json` : les pages « X ou Y ? » (paires de stratégies et textes) ;
- `site_config.json` : le nom du site (`site_name`), l'adresse publique du site (à changer si tu prends un nom de domaine), l'éditeur affiché dans les mentions légales et l'adresse GoatCounter.

Dans les textes des fiches et des règles, `[ADM](strategie:adm)` crée un lien vers une autre fiche et `[RotationShield](https://rotationshield.be)` un lien externe.

Fichiers fixes du site (à ne pas supprimer) : `site/fonts/` (polices IBM Plex hébergées sur le site, pas d'appel à Google), `site/favicon.svg`, `site/favicon-48.png`, `site/apple-touch-icon.png`. Les polices des images d'aperçu sont dans `assets/og-fonts/`.

Ne modifie pas les pages générées dans `site/` : elles sont réécrites à chaque exécution.

Pour voir le site en local : `cd site && python3 -m http.server 8000`, puis http://localhost:8000.

## Ajouter un ETF

Ajoute une ligne dans `universe.json`, puis lance `python3 fetch_data.py --only TICKER`.

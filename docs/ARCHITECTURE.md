# Architecture technique

```
┌──────────── App desktop (Tauri 2 · Rust) ────────────┐
│ fenêtre flottante sans bordure · zone de notification │
│ raccourci global → lit le presse-papiers → événement  │
│ lance le moteur Python (port libre + jeton aléatoire) │
│  ┌──── Interface React + TypeScript + Tailwind ────┐  │
│  │ Accueil · Fiche (10 onglets) · Historique ·     │  │
│  │ Narratives · Smart money · Performance · Param. │  │
│  └───────────── HTTP + WebSocket (127.0.0.1) ──────┘  │
└───────────────────────────┬───────────────────────────┘
                            │
┌──────────── Moteur d'analyse (Python · FastAPI) ─────┐
│ orchestrator.py : 12 modules en parallèle (asyncio)  │
│   N1 : launchpad · market · security · holders · liquidity      → 1re fiche
│   N2 : developer · social · clusters · narrative · smart_money
│   N3 : project · factcheck            → score recalculé à chaque module
│ engines/narratives.py : moteur continu (toutes les N min)       │
│ engines/tracker.py : relevés 5 min → 7 j, backtest, probabilités│
│ providers/ : RPC, DexScreener, GeckoTerminal, Jupiter, RugCheck,│
│   pump.fun, web (site, RDAP, oEmbed X, Telegram, Discord,       │
│   GitHub), news (GDELT, RSS, Reddit), LLM optionnel             │
│ SQLite (WAL) · keyring (secrets)                                │
└──────────────────────────────────────────────────────────────────┘
```

## Choix
- **Tauri plutôt qu'Electron** : installeur ~10 Mo vs ~100 Mo, RAM au repos bien plus faible, plugins officiels
  pour raccourci global, tray, presse-papiers, notifications, état de fenêtre.
- **Un backend modulaire plutôt que 15 microservices** : un seul utilisateur, donc un seul processus ; les 15 moteurs
  du cahier des charges sont des modules indépendants (`engines/`) aux mêmes frontières, séparables plus tard.
- **SQLite** plutôt que PostgreSQL/Redis/TimescaleDB : zéro installation, suffisant pour un usage individuel.
  Tables : celles du cahier des charges (sans `users`, inutile en local).

## Échanges entre modules
`engines/context.py` : chaque module publie des résultats intermédiaires (`ctx.provide("creator", …)`)
que d'autres attendent avec un délai maximal (`await ctx.need("creator", timeout=…)`). Aucun module n'attend
qu'un autre ait *fini* : ils démarrent tous en même temps.

## Traçabilité
Chaque valeur : `{"v": valeur, "src": source, "ts": horodatage, "st": statut}`. Le résultat complet (JSON) de chaque
analyse est stocké avec l'identifiant de version du modèle de scoring → analyse reproductible.

## Scoring
`engines/scoring.py`. Sous-scores 0–10 + confiance 0–1 par catégorie ; global = moyenne pondérée des catégories
disponibles ; confiance globale = couverture pondérée. Verdict :
- **AVOID** : risque critique, score < seuil, données insuffisantes, ou confiance trop faible en fin d'analyse ;
- **BUY SETUP** : score ≥ seuil **et** confiance ≥ seuil **et** risque ≤ tolérance ;
- **WATCH** sinon (les conditions manquantes sont listées).
Le score de risque (0–10) est séparé du potentiel. L'IA ne modifie jamais score ni verdict.

## Probabilités
`engines/tracker.py` : pour chaque horizon, échantillons triés chronologiquement, split 60/20/20,
probabilité par tranche de score (lissée vers le taux de base) ; publiée seulement si
n_test ≥ 100, Brier < Brier du taux de base, ECE < 0,1. Une hausse = +X % (paramétrable) après 2 % de frais estimés.

## Sécurité
- API locale : 127.0.0.1, contrôle de l'en-tête Host, jeton de session (comparaison à temps constant), CORS restreint.
- Contenus externes (tweets, sites, métadonnées) : traités comme texte non fiable ; jamais exécutés ;
  encadrés comme données dans les prompts IA (anti-injection) ; l'IA n'a aucun outil.
- Taille et délai maximum sur chaque téléchargement ; limitation de débit par fournisseur.
- Aucune dépendance de signature de transaction dans le moteur.

## Ajouter un launchpad
`providers/solana.py` → `PROGRAMS` (ID du programme) ; `engines/identify.py` → `detect_launchpad` (PDA connue)
ou la détection générique par transaction de création.

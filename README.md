# Solana AI Desktop Analyst

Petite application de bureau flottante qui analyse **à la demande** un token Solana à partir de son adresse Mint,
et rend une **note sur 10**, un **verdict** (BUY SETUP / WATCH / AVOID) et une analyse détaillée sourcée.

- **Lecture seule** : aucune clé privée, aucune signature, aucun achat. Le logiciel est un assistant de décision.
- **100 % gratuit** : uniquement des sources gratuites ou publiques (voir « Sources »).
- **Honnête par construction** : chaque donnée porte sa source, son horodatage et son statut
  (*observé / vérifié / estimé / non vérifié / indisponible*). Rien n'est inventé ; ce qui ne peut pas être vérifié
  est affiché **NON VÉRIFIÉ** ; aucune probabilité n'est affichée tant que le modèle n'est pas validé statistiquement.

---

## Installation (Windows)

### Option A — installeur (recommandé)
1. Mets ce dossier sur un dépôt GitHub (privé possible).
2. Onglet **Actions** → workflow **build** → *Run workflow* (gratuit). Ou crée un tag `v0.1.0`.
3. Télécharge l'artefact `installeur-windows-latest` → lance le `.exe` (NSIS) ou le `.msi`.

L'installeur contient tout (moteur d'analyse compris) : **pas besoin d'installer Python**.

> Windows SmartScreen peut avertir car l'installeur n'est pas signé (un certificat de signature est payant).
> « Informations complémentaires → Exécuter quand même ».

### Option B — mode développement
Prérequis : Python 3.11+, Node 20+, Rust (rustup).
```bash
cd backend && pip install -r requirements.txt
cd ../app && npm install
# Windows PowerShell : $env:ANALYST_BACKEND_DIR="..\backend" ; npx tauri dev
ANALYST_BACKEND_DIR=../backend npx tauri dev
```

## Configuration (facultative, gratuite)
Dans **⚙ Paramètres** :

| Réglage | Effet | Coût |
|---|---|---|
| **Clé Helius** (helius.dev, plan Free) | RPC plus rapide, nombre exact de holders, top 50, évaluation PnL des wallets smart money | gratuit |
| **IA** : Ollama (local), Groq, Gemini, OpenRouter | rédaction de la conclusion + extraction des affirmations à vérifier | gratuit (paliers gratuits) |
| Raccourci global | défaut `Ctrl+Shift+Espace` — à changer s'il entre en conflit avec ton terminal | — |
| Pondérations / seuils / tolérance au risque | chaque modification crée une **nouvelle version du modèle** (jamais silencieuse) | — |

Les clés sont stockées dans le **Gestionnaire d'identification Windows** (chiffré par le système), jamais en clair.

## Utilisation
1. Copie l'adresse Mint (ou un lien DexScreener / pump.fun / Solscan) dans ton terminal.
2. `Ctrl+Shift+Espace` : la fenêtre apparaît, l'adresse est collée et l'analyse démarre.
   Le presse-papiers n'est lu **qu'à ce moment-là**.
3. La première fiche s'affiche dès que marché + on-chain + sécurité sont prêts (objectif 5 s),
   puis se complète en direct (social, narrative, fact-check…). La durée réelle est affichée.

Pages : Historique (filtres + comparaison), Narratives mondiales (top 10), Smart money (wallets suivis),
Performance (backtesting), Paramètres.

## Ce que fait chaque module

| Module | Données | Source gratuite |
|---|---|---|
| Identification / launchpad | validité, existence du mint, programme Token, **launchpad vérifié on-chain** (bonding curve Pump.fun, pool LaunchLab/LetsBonk, transaction de création → Meteora DBC) | RPC Solana |
| Marché | prix, market cap ≠ FDV ≠ liquidité, volumes 1 min / 5 min / 15 min / 1 h / 24 h, transactions, acheteurs/vendeurs uniques, momentum, signaux d'activité artificielle | DexScreener, GeckoTerminal, bonding curve on-chain |
| Liquidité | **impact réel** d'un achat/vente de 0,5 / 2 / 10 SOL (devis, rien n'est exécuté), LP verrouillée | Jupiter, RugCheck |
| Sécurité | mint/freeze authority, Token-2022 (frais, hook, délégué permanent, pause…), métadonnées modifiables, 2ᵉ avis RugCheck | RPC + RugCheck |
| Holders | top 20 avec **exclusion des pools / bonding curve / burn / PDA**, total holders, top 50 (Helius) | RPC, RugCheck, Helius |
| Clusters | financement commun des gros wallets, wallets neufs — présentés comme **liens observés** | RPC |
| Développeur | créateur identifié on-chain, part détenue, historique de lancements (morts / migrés / durée de vie) → réputation ; sinon **NON IDENTIFIÉ** | RPC, pump.fun (API publique non officielle), DexScreener |
| Social | liens déclarés (DexScreener, métadonnées, pump.fun) ; site (adresse affichée ? âge du domaine), X (oEmbed public), Telegram (page publique), Discord (invitation publique), GitHub → 6 statuts d'authenticité | pages et API publiques |
| Fact-check | extraction des affirmations (IA ou règles) et recherche de sources indépendantes | Google News RSS, GDELT |
| Narratives | collecte continue, dédoublonnage des dépêches, accélération, cycle de vie (ÉMERGENTE → EN DÉCLIN), saturation (tokens Solana homonymes), corrélation avec le token | GDELT, Google News, RSS crypto, Reddit RSS, DexScreener |
| Smart money | wallets suivis présents sur le token ; PnL réalisé, win rate, périodes, frais (≥ 20 positions pour être « fiable ») | RPC, Helius |
| Scoring | 6 sous-scores + score de risque séparé, pondérations modifiables, confiance, verdict justifié | règles versionnées |
| Suivi & backtest | relevés à 5 min / 15 min / 1 h / 6 h / 24 h / 7 j, max/min, performance par score / verdict / launchpad / market cap, précision/rappel, **probabilités calibrées** (split chronologique, Brier, ECE) | DexScreener, GeckoTerminal |

## Limites assumées (version gratuite)
- **X / Twitter** : l'API officielle est payante. Seule l'existence d'un compte/tweet est vérifiée (oEmbed) ;
  ancienneté, audience et engagement ne sont **pas** mesurés et c'est affiché.
- **Instagram / TikTok** : pas d'accès public autorisé → NON VÉRIFIÉ.
- **Telegram / Discord** : seuls membres / en ligne publics ; l'activité des messages n'est pas lue.
- **Narratives** : les tendances nées uniquement sur X apparaissent quand médias/Reddit les reprennent.
- **Moteur de narratives et suivi des performances** : actifs uniquement quand l'application est ouverte
  (relevés en retard marqués « en retard » et exclus du calibrage).
- **Probabilités** : « DONNÉES INSUFFISANTES » tant qu'il n'y a pas ≥ 100 observations de test validées par horizon.
- **Stonk.fun** : programme non identifié à ce jour ; détection à ajouter (architecture prévue).
- Le **pump.fun frontend API** n'est pas officiel et peut changer ; il est désactivable.

## Données et confidentialité
Tout reste sur ton PC : base SQLite dans `%APPDATA%\SolanaAIDesktopAnalyst`, journaux dans
`%LOCALAPPDATA%\com.solanaanalyst.desktop\logs`. L'API locale écoute uniquement sur `127.0.0.1` et exige un jeton
de session aléatoire généré à chaque lancement.

## Mise à jour
1. Télécharge le nouvel installeur (Actions ou Releases) et lance-le : il remplace l'ancienne version.
2. Tes données (historique, wallets, paramètres, clés) sont conservées.
3. Les versions du modèle de scoring sont historisées (page Performance).

## Tests
```bash
cd backend && python -m pytest -q tests     # 16 tests : analyse de bout en bout sur faux réseau, pannes, risques…
cd app && npm run build                       # vérification TypeScript + build
python -m tests.demo_server                   # (dans backend/) interface de démo sans Internet
```
Voir `docs/ARCHITECTURE.md` pour la documentation technique.

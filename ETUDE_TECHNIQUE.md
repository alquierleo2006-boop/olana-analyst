# Solana AI Desktop Analyst — Étude technique préalable

> Réponse à la Partie 20 du cahier des charges. Objectif : valider l'architecture, les fournisseurs,
> les coûts et ce qui est réellement faisable **avant** de coder.
> Les prix et limites d'API changent souvent : chaque chiffre marqué *(à vérifier)* doit être
> confirmé sur le site du fournisseur au moment de souscrire.

---

## 1. Synthèse : ce qui est faisable, et à quelles conditions

| Bloc du cahier des charges | Faisabilité | Commentaire |
|---|---|---|
| App desktop flottante, raccourci global, presse-papiers à la demande | ✅ Simple | Tauri 2 le fait nativement (plugins `global-shortcut`, `clipboard-manager`, `window-state`, tray). |
| Identification du token + launchpad (Pump.fun, LetsBonk, Meteora DBC) | ✅ | Via le programme on-chain qui a créé le mint / la bonding curve, pas via le nom. Stonk.fun : programme à identifier. |
| Marché, liquidité, volumes, transactions | ✅ en < 5 s | DexScreener / Birdeye / GeckoTerminal + RPC Helius en parallèle. Volume **1 min** : seulement via Birdeye (payant) ou reconstruction depuis les transactions. |
| Holders, concentration, exclusion des pools | ✅ | `getTokenLargestAccounts` + identification des comptes de pool/programme. **Nombre total de holders** : nécessite Helius DAS ou Birdeye (pas fiable en RPC brut). |
| Sécurité technique (authorities, Token-2022, transfer fees, hooks) | ✅ | Lecture directe du mint + RugCheck en 2ᵉ source. |
| Profil du développeur (tokens précédents, ventes, durée de vie) | ✅ mais coûteux | Historique des transactions du wallet créateur via Helius. Premier passage 2–8 s, ensuite mis en cache. |
| Clusters de wallets liés | 🟡 Partiel | Financement commun + achats groupés au lancement : faisable. Présenté comme **observation**, jamais comme preuve. Bubblemaps API en complément (payant). |
| Analyse X / Twitter | 🟡 Dépend du budget | L'API X officielle est payante et limitée en recherche *(à vérifier, plusieurs centaines $/mois pour un usage utile)*. Sans elle : seul ce qui est public via les liens du token. |
| Instagram, TikTok | 🔴 Très limité | Pas d'API publique de recherche pour cet usage. On pourra seulement vérifier qu'un lien déclaré existe. Affiché **NON VÉRIFIÉ** sinon. |
| Telegram, Discord | 🟡 Partiel | Membres d'un groupe public : possible. Activité réelle des messages : seulement si un compte/bot à toi est **dans** le groupe. Pas de contournement. |
| Fact-checking | 🟡 | Recherche web (API de recherche) + LLM pour extraire les affirmations et comparer aux sources. Qualité correcte, jamais garantie → statuts du cahier des charges. |
| Narratives mondiales | ✅ / 🟡 | GDELT (gratuit), RSS, Reddit, Google Trends non officiel exclu. X améliore beaucoup, mais selon le budget. |
| Smart money (PnL, win rate) | 🟡 Lourd | Reconstruire le PnL de chaque wallet demande beaucoup d'appels. Faisable pour une liste de wallets suivis (dizaines/centaines), pas pour « tout le marché ». |
| Score /10 et verdict | ✅ | Règles transparentes + pondérations modifiables dès la v1. |
| **Probabilités de hausse calibrées** | 🔴 Pas au départ | Impossible honnêtement sans historique étiqueté. La v1 affichera « DONNÉES INSUFFISANTES ». Elles deviennent possibles après plusieurs centaines d'analyses suivies dans le temps (Partie 11), ou via un jeu historique Pump.fun (voir §6). |
| 5 s memecoin / 15 s projet | ✅ pour la 1ʳᵉ fiche | Niveau 1 (marché + on-chain + sécurité) en 2–4 s. Social, fact-check et synthèse IA arrivent ensuite en flux, la fiche affichant clairement « provisoire ». |

---

## 2. Choix technologiques

### Desktop : **Tauri 2 + React + TypeScript + Tailwind** (retenu)

| Critère | Tauri 2 | Electron |
|---|---|---|
| Taille installeur | ~5–15 Mo | ~80–150 Mo |
| RAM au repos | ~50–100 Mo | ~200–400 Mo |
| Démarrage | Rapide | Plus lent |
| Raccourci global, tray, always-on-top, mémorisation de position | Plugins officiels | Natif |
| Mises à jour auto | Plugin `updater` | `electron-updater` |
| macOS | Oui | Oui |

Electron n'apporte rien d'indispensable ici. Tauri correspond mieux à « léger et rapide ».

### Backend : **un seul service Python (FastAPI) modulaire**, pas 15 microservices

Le cahier des charges liste 15 services. Pour **un seul utilisateur**, en faire 15 processus séparés
ajoute de la complexité, de la latence et des pannes sans bénéfice. Je recommande :

- **Un backend FastAPI** contenant les 15 moteurs comme **modules** indépendants (mêmes frontières, même découpage, testables séparément), exécutés en parallèle avec `asyncio`.
- **WebSocket** vers l'app : la fiche se remplit au fur et à mesure (niveau 1 → 2 → 3).
- **Base de données** : SQLite si tout tourne sur ton PC ; PostgreSQL (+ TimescaleDB) si un serveur est utilisé (§3).
- **Cache** en mémoire au départ ; Redis seulement si un serveur est utilisé.

Si un jour le produit devient multi-utilisateurs, les modules se séparent facilement en services.

### IA

- **Synthèse, extraction d'affirmations, analyse de publications, verdict rédigé** : un LLM (ex. API Claude), avec sortie structurée JSON.
- **Le score n'est pas inventé par le LLM** : il est calculé par des règles et pondérations explicites. Le LLM explique et classe, il ne fabrique pas de chiffres.
- Toutes les données externes (tweets, sites, métadonnées) sont passées au LLM comme **données non fiables**, jamais comme instructions (protection contre l'injection de prompt, Partie 15).

---

## 3. Décision clé : où tourne le moteur de narratives ?

Le cahier des charges veut un moteur de narratives **permanent**, indépendant des analyses.

| Option | Avantages | Inconvénients |
|---|---|---|
| **A. Tout sur ton PC** | Gratuit, simple, données locales | Le moteur ne surveille que **quand l'app est ouverte**. À l'ouverture, il rattrape (GDELT/RSS gardent l'historique), mais les tendances de la nuit sont moins précises. |
| **B. Petit serveur (VPS ~5–20 €/mois)** pour narratives + suivi des performances (5 min → 7 j) | Surveillance 24/7, historique complet, l'app desktop reste légère | Coût et un peu de maintenance |

Point important : le **suivi de performance après 6 h / 24 h / 7 jours** (Partie 11), indispensable au backtesting
et aux futures probabilités, ne fonctionne bien qu'en continu. → **Je recommande B**, en commençant par A si tu veux démarrer sans coût.

---

## 4. Fournisseurs de données et coûts estimés *(tous à vérifier)*

| Besoin | Principal | Secours | Coût indicatif |
|---|---|---|---|
| RPC, transactions parsées, DAS (holders, assets du créateur) | Helius | RPC public, autre RPC (Triton, QuickNode) | Gratuit pour démarrer ; ~50 $/mois au palier développeur |
| Marché, paires, liquidité | DexScreener | GeckoTerminal | Gratuit (limites de requêtes) |
| OHLCV fin, volume 1 min, holders count, traders | Birdeye | Reconstruction via Helius | Palier gratuit limité ; payant pour un usage réel |
| Quote / impact de prix réel | Jupiter | — | Gratuit (lite) |
| Sécurité | Lecture directe du mint + RugCheck | — | Gratuit |
| Clusters / bubble map | Analyse maison | Bubblemaps API | Bubblemaps payant |
| X / Twitter | API officielle X | Liens publics seulement | **Poste le plus cher** — plusieurs centaines $/mois pour de la recherche utile |
| Actualités | GDELT + RSS | NewsAPI / alternatives | GDELT gratuit ; NewsAPI payant en production |
| Reddit | API Reddit | — | Gratuit pour un usage perso limité |
| Recherche web (fact-check) | API de recherche (Brave, Tavily, Exa…) | — | ~0–50 $/mois selon volume |
| LLM | API Claude | Autre fournisseur | Quelques centimes par analyse ; dépend du volume |

**Fourchettes mensuelles** :
- **Minimal** (sans API X, sans Birdeye payant) : ~0–60 $/mois + LLM. Social limité à la vérification des liens déclarés.
- **Recommandé** (Helius dev + Birdeye + recherche web + LLM, sans X) : ~100–200 $/mois.
- **Complet** (avec API X utile) : plusieurs centaines de $/mois de plus.

---

## 5. Points techniques importants

- **Détection du launchpad** : par le programme propriétaire de la bonding curve / du pool d'origine.
  Programmes connus : Pump.fun (`6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P`), Raydium LaunchLab (utilisé par LetsBonk),
  Meteora DBC. Le suffixe `…pump` du mint est un **indice**, pas une preuve. Stonk.fun : programme à identifier en phase 2.
  Architecture en « détecteurs » enfichables pour ajouter d'autres launchpads.
- **Market cap vs FDV vs liquidité** : calculés et affichés séparément, chacun avec sa source et son horodatage.
- **Tokens en bonding curve** (pas encore migrés) : DexScreener ne les a parfois pas ; il faut lire la bonding curve on-chain directement pour le prix et la progression.
- **Traçabilité** : chaque valeur stockée = `{valeur, source, horodatage, statut vérifié/non vérifié}`. Les analyses sont reproductibles à partir des snapshots enregistrés.
- **Aucune clé privée, aucune signature** : le backend n'embarque aucune bibliothèque de signature de transaction. (L'outil terminal `memetrader` fait précédemment est un projet séparé et n'est pas réutilisé pour ses fonctions d'achat.)

---

## 6. Probabilités de hausse : plan honnête

1. **v1** : aucune probabilité affichée → « DONNÉES INSUFFISANTES POUR UNE PROBABILITÉ FIABLE ».
2. Chaque analyse est suivie automatiquement (5 min, 15 min, 1 h, 6 h, 24 h, 7 j) → constitution du jeu de données.
3. **Option d'accélération** : construire un jeu historique à partir de tokens Pump.fun passés (Bitquery, Dune ou Helius), en reconstituant les données **telles qu'elles étaient au moment t** (sans fuite d'information future). Utile, mais biaisé par rapport à tes choix de tokens : à combiner avec ton propre historique.
4. Modèle simple et calibré (régression logistique / gradient boosting + calibration), split **chronologique** entraînement/validation/test, métriques publiées (calibration, précision, rappel, résultats après frais).
5. Une probabilité n'est affichée pour un horizon que si le modèle a passé les seuils de validation, avec le nombre d'observations comparables.

---

## 7. Planning réaliste (développement assisté par IA, validation à chaque étape)

| Phase | Contenu | Durée indicative |
|---|---|---|
| 1 | App desktop : fenêtre flottante, tray, raccourci, validation Mint, historique, design | 1–2 semaines |
| 2 | Analyse Solana : identification, launchpad, marché, liquidité, holders, dev, sécurité, score v1 | 2–3 semaines |
| 3 | Social : liens déclarés, X (si API), Telegram/Discord accessibles, classification d'authenticité | 2–3 semaines |
| 4 | Fact-checking | 1–2 semaines |
| 5 | Narratives mondiales + corrélation | 2–3 semaines |
| 6 | Scoring complet, verdict IA, confiance | 1–2 semaines |
| 7 | Smart money, suivi de performance, backtesting | 2–4 semaines |
| 8 | Notifications, optimisation, tests, installeur Windows, mises à jour | 1–2 semaines |

Les phases 1 et 2 donnent déjà un outil **utile au quotidien** (score on-chain + sécurité + marché en quelques secondes).

---

## 8. Risques de développement

- **Coût et accès à l'API X** : principal risque pour la partie sociale.
- **Changements d'API** des launchpads et fournisseurs → couche d'adaptateurs + fournisseurs de secours.
- **Limites de requêtes** (rate limits) qui menacent l'objectif des 5 s → cache, priorisation niveau 1.
- **Faux sentiment de sécurité** : un score élevé ne protège pas d'un rug. Les risques critiques restent toujours affichés en tête de fiche.
- **Build Windows** : l'installeur Windows sera produit via GitHub Actions (Windows runner), pas dans l'environnement de développement Linux.

---

## 9. Décisions à prendre avant la phase 1

1. **Budget mensuel API** (minimal / recommandé / complet, avec ou sans X).
2. **Où tourne le moteur** : tout sur PC, ou PC + petit serveur.
3. **Fournisseur IA** (ex. API Claude) et clé API.
4. **Dépôt GitHub** pour sauvegarder le code (l'environnement de développement actuel est temporaire) et compiler l'installeur Windows.

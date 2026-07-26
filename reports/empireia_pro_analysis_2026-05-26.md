# Analyse — EA MT5 `EmpireIA_Pro`

**Investigation** : 2026-05-26, strictement en lecture seule.
**Sources** : code source MQL5, fichiers de configuration du tester, code Python `orchestrator/`, `utils/mt5_client.py`, `utils/sync_history.py`.

---

## 1. Localisation des fichiers

| Fichier | Chemin complet | Taille | Dernière modif |
|---|---|---:|---|
| Source MQL5 | `C:\Users\Kévin\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Experts\Advisors\EmpireIA_Pro.mq5` | 22 004 o | **2025-08-06** |
| Binaire compilé | `…\MQL5\Experts\Advisors\EmpireIA_Pro.ex5` | 39 564 o | **2025-08-06** |
| Binaire dupliqué | `…\MQL5\EmpireIA_Pro.ex5` | — | — |
| Profile tester | `…\MQL5\Profiles\Tester\EmpireIA_Pro.set` | — | 2025-07-25 17:52 |
| Backtests cache | `…\Tester\cache\EmpireIA_Pro.<SYMBOL>.<TF>.<dates>.tst` | — | — |

L'EA a été **compilé pour la dernière fois le 6 août 2025**. Aucun fichier dans `MQL5/Files/` (dossier où il écrirait `EmpireIA_Backtest.csv` quand attaché à un chart).

---

## 2. Mode de communication entre l'EA et le bot Python

**Verdict : aucune communication. Les deux systèmes sont totalement indépendants et coexistent en silos sur le même compte MT5.**

### 2.1 Côté EA (`EmpireIA_Pro.mq5`)
- **N'ouvre aucun fichier signal venant de Python** (pas de `FileOpen` sur un chemin Python, pas de socket, pas d'API HTTP, pas de DB).
- Déclare `string ConfigFile = "EmpireIA_Config.csv";` (ligne 54) **mais cette variable n'est référencée nulle part ailleurs dans le code** — c'est un reliquat non utilisé.
- Le seul I/O fichier est **un écriture sortante** : `EmpireIA_Backtest.csv` (ligne 55, fonction `ExportTrade` lignes 106-123) — un journal de ses propres trades, jamais relu par Python.
- Exécute ses ordres via la library standard `CTrade` (`trade.Buy(...)`, `trade.Sell(...)`).

### 2.2 Côté Python (`orchestrator/orchestrator.py` + `utils/mt5_client.py`)
- Communique avec MT5 via le package Python `MetaTrader5` (`mt5.order_send(...)`, `mt5.history_deals_get(...)`).
- 0 référence à `EmpireIA_Pro`, `EmpireIA_Config`, `EmpireIA_Backtest`, ou à un quelconque mécanisme de signal-vers-EA dans tout le repo (`grep -r EmpireIA`, hors logs d'archive). 
- Place les ordres avec `magic=0` (`utils/mt5_client.py:1181, 1335`).
- `utils/sync_history.py:17` lit `mt5.history_deals_get(start, end)` qui retourne **tous** les deals du compte broker — peu importe l'origine (EA ou Python). Donc `data/deals_history.csv` mélange les deux.

### 2.3 Conséquence directe
**Le deal SP500 du 19 mai 2026 22:59:44 UTC (+4.49 USD) visible dans `deals_history.csv` est probablement issu de l'EA `EmpireIA_Pro`, pas de l'orchestrator Python.** Cohérent avec le fait qu'empire_agent.log n'a aucune trace d'activité Python ce soir-là. La synchronisation `sync_history.py` ramasse ces deals EA et les met dans le CSV partagé, ce qui crée la confusion.

**Limite de discrimination** : l'EA utilise `CTrade` par défaut (qui place `magic=0`), et le Python place aussi `magic=0`. Impossible de distinguer les deux origines a posteriori sans lire le champ `comment` ou regarder les TP/SL spécifiques.

---

## 3. Symbole(s) et timeframe(s) attendus

**L'EA travaille sur le symbole et le timeframe du graphique auquel il est attaché**, déterminé dynamiquement via `_Symbol` et `PERIOD_CURRENT` (lignes 68-79 dans `OnInit`).

**Indices sur les usages testés** (fichiers de cache du tester) :
- **Symbole principal backtesté : BTCUSD** (la plupart des `.tst` et `.ini`)
- Un test sur **EURUSD H1**
- Timeframes backtestés : **M1, M30, H1, H4, Daily**
- Fenêtres testées : 2024-07 → 2025-07 et 2025-01 → 2025-07

→ En production, **un seul instance d'EA est attaché à un seul graphique à la fois** (limitation standard MT5). Pour trader 9 symboles, il faudrait l'attacher à 9 graphiques avec 9 jeux de paramètres différents.

---

## 4. Logique de trading : indépendante ou dépendante du Python ?

**Totalement indépendante.** L'EA est un classique EA mono-stratégie qui calcule ses propres signaux à chaque tick.

### 4.1 Stratégies disponibles (sélection par input `Strategy`)
Une seule à la fois — switch sur le nom de stratégie via `StringFind` :

| Stratégie | Logique | Indicateurs |
|---|---|---|
| `scalping` | EMA Fast/Slow + RSI overbought/oversold | EMA(21), EMA(50), RSI(7), ATR(14) |
| `swing` | Prix vs EMA(50) + RSI long/short threshold | EMA(50), RSI(14), ATR(14) |
| `technical` | EMA + MACD + RSI extrêmes | EMA(50), MACD(12,26,9), RSI(14), ATR(14) |
| `sentiment` | **Aléatoire** (MathRand < SENTI_LONG_FREQ=0.10) | ATR |
| `news` | **Aléatoire** (MathRand < NEWS_FREQ=0.08) | ATR |
| `fundamental` | **Aléatoire** (MathRand < FUND_FREQ=0.08) | ATR |

⚠️ Les stratégies `sentiment`, `news` et `fundamental` génèrent leurs entrées **purement aléatoirement** (commentaires du code : *"synthetic, backtest = signaux simulés"*). Elles ne sont pas exploitables en live.

### 4.2 Gestion des positions
- Lot : `RiskPercent (1.0%) × accountBalance` / stop distance (calculé à l'init seulement, balance figée).
- TP/SL : multiples d'ATR (configurable).
- BE après TP1 : à TP1, ferme `PartialClose=0.5` (50%) et place SL au break-even (lignes 275-292 `ManageOpenPosition`).
- **Un seul trade par symbole à la fois** : `PositionSelect(_Symbol)` retourne immédiatement si une position est ouverte (ligne 129).

### 4.3 Outputs
- Print dans le journal MT5 (Expert tab).
- Append CSV `EmpireIA_Backtest.csv` (dans `MQL5/Files/`).

---

## 5. Recommandation pour réactiver le système

### ⚠️ Conflit potentiel à anticiper
Si l'EA et le bot Python tournent **en même temps sur le même compte MT5**, deux risques majeurs :

1. **Double position involontaire** : l'EA n'inhibe pas les positions ouvertes par d'autres systèmes. Si Python ouvre BTCUSD et l'EA ouvre BTCUSD ensuite, vous aurez deux positions cumulées. Le risque réel sera double.

2. **Fermetures croisées** : le `PositionManager` Python (`utils/position_manager.py`) scanne **toutes** les positions ouvertes sur le compte. Si l'EA ouvre une position avec `magic=0` et `comment` vide, Python peut la prendre pour une de ses propres positions et la fermer (trailing, BE, partial). À l'inverse, l'EA ne fermera **que ses propres** positions (via `PositionSelect(_Symbol)`).

### Options de réactivation

**Option A — Réactiver uniquement le bot Python (recommandé)**
- Ne **pas** attacher l'EA à un graphique.
- Le bot Python est déjà actif depuis 19:19:51 ce 26 mai et tourne correctement (cf. `reports/diagnostic_redemarrage_2026-05-26.md`).
- Le `magic=0` Python reste, mais sans EA en parallèle il n'y a pas de conflit.

**Option B — Réactiver uniquement l'EA (le système qui tradait jusqu'au 19 mai)**
- Arrêter le bot Python (ou désactiver `auto_execute` dans `config/overrides.yaml`).
- Attacher manuellement `EmpireIA_Pro` à un graphique (vous l'avez signalé : c'est vous qui le ferez).
- Choisir la stratégie via input `Strategy` (éviter `sentiment`, `news`, `fundamental` qui sont aléatoires).
- Limitation : un seul symbole tradé à la fois par instance.

**Option C — Faire coexister les deux (déconseillé en l'état)**
- Implique au minimum :
  - **Différencier les magic numbers** : modifier l'EA pour utiliser `trade.SetExpertMagicNumber(<unique>)` et configurer Python avec un magic différent (ex : Python `magic=10001`, EA `magic=20001`).
  - **Filtrer le PositionManager Python** sur son propre magic uniquement, sinon il agira aussi sur les trades EA.
  - **Filtrer `sync_history.py`** par magic si vous voulez séparer les historiques.
- Ces modifications sortent du périmètre lecture-seule de la demande actuelle. À planifier comme un projet à part entière.

### Question à clarifier avant action
- Sur **quel symbole et timeframe** l'EA tradait-il le 19 mai à 22:59 ? Le deal SP500 visible dans `deals_history.csv` suggère que l'EA était attaché à SP500 à ce moment-là — mais le seul fichier `.set` connu (`EmpireIA_Pro.set`) montre des paramètres BTCUSD du tester. Donc l'instance qui a tradé SP500 utilisait probablement un autre jeu de paramètres saisi à la main lors de l'attachement.
- Si vous voulez reprendre exactement le système qui fonctionnait : il faudrait connaître la stratégie sélectionnée et les paramètres saisis sur ce graphique SP500.

### Note sur le fichier `EmpireIA_Config.csv` (mort-né)
Le code MQL5 déclare `string ConfigFile = "EmpireIA_Config.csv";` mais ne lit jamais ce fichier. Si l'intention historique était une communication par CSV depuis Python, **elle n'a jamais été implémentée côté EA**. Donc impossible de "réactiver" un canal de signal Python → EA : ce canal n'existe pas dans le binaire actuel.

---

## 6. Limites de cette investigation

- **Source MQL5 lue mais binaire `.ex5` non décompilé** : si le `.ex5` a été modifié sans recompiler le `.mq5` (rare mais possible), le comportement réel pourrait diverger légèrement de ce que ce rapport décrit.
- **Aucun log MT5 lu** : les journaux Expert MT5 (`MQL5/Logs/<date>.log`) n'ont pas été inspectés ; ils confirmeraient le moment exact où l'EA était attaché et sur quel symbole.
- **Pas d'inspection des positions broker actuelles** : impossible de savoir en lecture-seule du repo si une position EA est ouverte. À vérifier dans la plateforme MT5.

---

## 7. Réponses synthétiques aux 5 questions du livrable

1. **Localisation EA** : `C:\Users\Kévin\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Experts\Advisors\EmpireIA_Pro.mq5` (source) et `.ex5` (compilé 2025-08-06).

2. **Mode de communication** : **aucun**. L'EA est indépendant du Python ; ils coexistent en silos sur le même compte MT5.

3. **Symbole/timeframe** : dynamique selon le graphique d'attache. Backtests historiques principalement sur **BTCUSD** (M1/M30/H1/H4/Daily) et **EURUSD H1**.

4. **Logique indépendante** : oui, 100 %. L'EA calcule ses propres signaux (EMA/RSI/MACD/ATR selon la stratégie). Les modes `sentiment`/`news`/`fundamental` sont **aléatoires** (à proscrire en live).

5. **Recommandation** : **Option A** (Python seul, ne pas attacher l'EA) — c'est l'état actuel et le bot Python tourne déjà correctement depuis 19:19. Si vous voulez revenir au mode "EA seul" du 19 mai, choisir **Option B** après désactivation du Python. **Option C** (les deux ensemble) demande une refonte du magic-numbering avant de pouvoir être envisagée sans risque de conflit.

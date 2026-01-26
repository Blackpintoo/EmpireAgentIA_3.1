# 🔍 DIAGNOSTIC EMPIRE AGENT IA v3 - 1er Décembre 2025

## ❌ PROBLÈMES IDENTIFIÉS

### 1. Daily Digest ne s'envoie pas

**Problème** : Avec 16 orchestrateurs en parallèle, chacun essaye de créer son propre scheduler de digest.

**Ligne problématique** : `orchestrator.py:773`
```python
syms = [getattr(self, "symbol", "BTCUSD")]  # ❌ Chaque orchestrateur ne fait le digest que pour SON symbole
```

**Conséquence** : 16 jobs de digest séparés au lieu d'un seul global.

**Solution** : Créer UN SEUL scheduler de digest global pour tous les symboles.

---

### 2. Aucun trade exécuté

**Causes possibles** :
1. **Confluence insuffisante** : `votes_required=2` mais peut-être qu'aucun agent ne vote
2. **Sessions fermées** : Symboles hors horaires de trading
3. **Cooldown actif** : Période de refroidissement après événement
4. **Risk Management bloque** : Limites quotidiennes atteintes
5. **Signaux faibles** : Score < `min_score_for_proposal` (2.0)

**Logs manquants** : Impossible de diagnostiquer sans voir les logs de la console actuelle.

---

### 3. Logs non sauvegardés

**Problème** : Variable d'environnement `EMPIRE_LOG_FILE` non définie.

**Conséquence** : Les logs sont seulement dans la console, pas dans un fichier.

**Solution** : Ajouter logging dans fichier.

---

## 🔧 CORRECTIONS À APPLIQUER

### Correction 1 : Daily Digest Global

Modifier `main.py` pour créer un seul scheduler de digest pour TOUS les symboles :

```python
# Après création des orchestrateurs
from apscheduler.schedulers.background import BackgroundScheduler
from reporting.daily_digest import send_daily_digest
import pytz

def create_global_digest_scheduler(orchestrators, enabled_symbols):
    """Crée UN SEUL scheduler de digest pour tous les symboles"""

    cfg = yaml.safe_load(open("config/config.yaml", encoding="utf-8"))
    tg_config = cfg.get("telegram", {})

    if not tg_config.get("send_daily_digest", False):
        logger.info("[DIGEST] Daily digest désactivé dans config")
        return None

    # Récupérer les horaires
    raw_times = tg_config.get("daily_digest_times", ["10:00", "19:00"])
    if not isinstance(raw_times, list):
        raw_times = [raw_times]

    # Créer scheduler
    tz = pytz.timezone("Europe/Zurich")
    digest_scheduler = BackgroundScheduler(timezone=tz)

    # Utiliser le premier orchestrateur pour l'envoi Telegram
    first_orch = orchestrators[0] if orchestrators else None

    def digest_job(hour, minute):
        logger.info(f"[DIGEST] Génération digest {hour:02d}:{minute:02d} pour {len(enabled_symbols)} symboles")
        if first_orch:
            send_daily_digest(first_orch._send_telegram, enabled_symbols, tz_name="Europe/Zurich")

    # Ajouter les jobs
    for time_str in raw_times:
        try:
            hh, mm = map(int, time_str.split(":"))
            job_id = f"global_digest_{hh:02d}{mm:02d}"
            digest_scheduler.add_job(
                digest_job,
                "cron",
                id=job_id,
                hour=hh,
                minute=mm,
                args=(hh, mm)
            )
            logger.info(f"[DIGEST] Job programmé : {time_str}")
        except Exception as e:
            logger.error(f"[DIGEST] Erreur programmation {time_str} : {e}")

    digest_scheduler.start()
    logger.info(f"[DIGEST] Scheduler démarré pour {len(raw_times)} horaires")
    return digest_scheduler

# Dans main()
digest_sched = create_global_digest_scheduler(orchestrators, enabled_symbols)
```

---

### Correction 2 : Désactiver Digest dans orchestrateur

Modifier `orchestrator/orchestrator.py` ligne 751-798 pour ne PAS créer de digest si multi-symboles :

```python
def _maybe_schedule_daily_digest(self):
    """
    NE RIEN FAIRE si lancé en multi-symboles.
    Le digest global est géré dans main.py
    """
    # Vérifier si c'est un lancement multi-symboles
    import sys
    if len(sys.argv) > 1 and '--multi-symbols' in sys.argv:
        logger.info("[DIGEST] Mode multi-symboles détecté, digest géré globalement")
        return

    # Code original uniquement pour lancement single-symbole
    # ... (garder le code existant)
```

---

### Correction 3 : Logging dans fichier

Ajouter dans `.env` :

```bash
# Fichier de logs
EMPIRE_LOG_FILE=logs/empire_agent.log
EMPIRE_CONSOLE=1
EMPIRE_LOG_LEVEL=INFO
```

---

### Correction 4 : Diagnostic des signaux

Ajouter plus de logs dans `orchestrator.py` pour comprendre pourquoi aucun trade :

```python
# Dans _run_agents_and_decide, après ligne 1500
logger.info(f"[ORCH] {self.symbol} - Analyse agents en cours...")

# Après collecte des signaux
logger.info(f"[ORCH] {self.symbol} - Signaux collectés : {len(per_tf_signals)} agents")

# Après calcul votes
if votes_for_buy > 0 or votes_for_sell > 0:
    logger.info(f"[ORCH] {self.symbol} - Votes : BUY={votes_for_buy} SELL={votes_for_sell} (requis={self.votes_required})")
else:
    logger.debug(f"[ORCH] {self.symbol} - Aucun vote (confluence insuffisante)")
```

---

## 📊 VÉRIFICATIONS À FAIRE

### 1. Dans la console Windows actuellement

Cherchez ces messages :
```
[Digest] summary triggered (10:00)
[Digest] summary triggered (19:00)
```

Si absent → Le scheduler ne démarre pas

### 2. Cherchez les raisons de non-trade

```
[ORCH] BTCUSD - votes_for_buy=X votes_for_sell=Y (required=2)
[PHASE4] Trading not allowed for XXX: reason
[COOLDOWN] XXX actif ~X min → skip cycle
[RISK] Conditions non remplies
```

### 3. Vérifiez config.yaml

```yaml
telegram:
  send_daily_digest: true  # ✅ DOIT être true
  daily_digest_times: ["10:00", "19:00"]  # ✅ DOIT être défini
```

### 4. Vérifiez votes_required

```yaml
orchestrator:
  votes_required: 2  # Peut-être trop élevé ?
  min_score_for_proposal: 2.0  # Peut-être trop élevé ?
```

---

## 🔥 ACTIONS IMMÉDIATES

1. ✅ Arrêter le bot actuel
2. ✅ Appliquer les corrections ci-dessus
3. ✅ Relancer et surveiller les logs console
4. ✅ Noter TOUS les messages dans les logs
5. ✅ Partager les logs avec moi pour diagnostic précis

---

## 📝 QUESTIONS POUR DIAGNOSTIC

1. **Voyez-vous ces messages au démarrage ?**
   - `[DIGEST] Job programmé : 10:00`
   - `[DIGEST] Job programmé : 19:00`
   - `[DIGEST] Scheduler démarré pour 2 horaires`

2. **Voyez-vous des analyses d'agents ?**
   - `[ORCH] BTCUSD - Analyse agents en cours...`
   - `[Agent] scalping signal: BUY/SELL`

3. **Voyez-vous des sessions fermées ?**
   - `[PHASE4] Trading not allowed for XXX`

4. **Config Telegram dans config.yaml ?**
   - `send_daily_digest: true` ?
   - `daily_digest_times: ["10:00", "19:00"]` ?

---

**Date** : 2025-12-01
**Système** : Empire Agent IA v3 - Mode RÉEL
**Statut** : ⚠️ Fonctionnement partiel - Corrections requises

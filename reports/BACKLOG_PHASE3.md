# Backlog Phase 3 — EmpireAgentIA 3.1

**Date de création** : 2026-05-05
**Origine** : sujets identifiés pendant le cycle Phase 1 + Phase 2 et 
non traités à ce jour.
**Lecture recommandée** : à relire avant le déclenchement de la 
Directive 12 (vers 2026-05-19).

---

### 1. Investigation perte NAS100 -227 USD du 4 mai 2026

**Description** : Trade NAS100 LONG du 2026-05-04 a touché le SL en 
moins de 10 minutes pour une perte de 227 USD, soit près de 50 % du 
P&L négatif total des 95 premières heures post-Phase 1. À analyser 
isolément pour distinguer un événement macro/gap d'une entrée prise 
sur du bruit.
**Priorité** : P2
**Condition de déclenchement** : à inspecter dès le prochain debrief, 
avec extraction du contexte de marché (économie, gap, news) et des 
scores agents au moment de l'entrée.

### 2. Régression P&L globale post-Phase 1

**Description** : -465 USD sur 95h vs baseline qui faisait du léger 
positif. L'avg_win est en baisse de 35 % (116 → 75 USD), suggérant 
que les nouveaux partials à 1.0R/1.8R coupent les runners qui 
faisaient la profitabilité. À reconfirmer sur n > 100 trades.
**Priorité** : P1
**Condition de déclenchement** : analyse complète à n=100 trades 
post-Phase 1 (estimé vers J+10 à J+14). Si confirmé, envisager de 
différer le 1er partial à 1.2R ou de réduire close_frac à 0.15.

### 3. Reformulation Directive 9 — retcode 10016 cryptos

**Description** : Le brief original de la Directive 9 visait le 
retcode 10030 (filling_type) mais l'analyse a révélé que le vrai 
problème est le retcode 10016 (stops invalides) sur LTCUSD/SOLUSD/
BNBUSD, qui représente 91 % des échecs MT5. À traiter en relevant 
la distance min SL pour ces cryptos via atr_sl_mult ou un 
trade_stops_level_safety_margin.
**Priorité** : P1
**Condition de déclenchement** : Phase 3, à lancer après J+14.

### 4. Optimisation paramètres ATR pour BNBUSD et SOLUSD

**Description** : Ces deux symboles sont en shadow mode depuis le 
30 avril précisément pour permettre cette optimisation basée sur 
données. Le script Directive 12 doit simuler les multiplicateurs 
alternatifs (1.5×, 2.0×, 2.5×, 3.0×) sur les propositions shadow 
et identifier le multiplicateur qui donne WR > 40 % et R:R > 1.4.
**Priorité** : P1
**Condition de déclenchement** : J+14 (lancement Directive 12). 
Réactivation conditionnelle après validation par les chiffres.

### 5. Investigation heure 18 UTC négative

**Description** : -467 USD sur 14 trades à h18 UTC alors que 
c'était un pilier profitable du baseline (+3 675 sur 37 trades). 
À reconfirmer sur n > 30 avant action. Si la régression se confirme, 
candidate à l'ajout dans la blacklist horaire globale.
**Priorité** : P2
**Condition de déclenchement** : analyse hebdomadaire des 
performances par heure UTC, dès n=30 trades sur h18 atteints.

### 6. Régression du ratio trailing au lieu de la hausse attendue

**Description** : Le ratio des trades sortis en trailing est passé 
de 13.9 % à 11.8 % alors que la Directive 3 visait l'inverse. 
Hypothèse : interaction BE 1.5R / partial 1.8R / trailing 1.0R qui 
laisse une fenêtre étroite au trailing. À investiguer en extrayant 
les trades sortis en BE+offset et en vérifiant combien auraient été 
éligibles au trailing si le BE avait été à 1.8R ou 2.0R.
**Priorité** : P2
**Condition de déclenchement** : analyse à n > 100 trades 
post-Phase 1, conjointement au sujet n°2.

### 7. Rotation des logs

**Description** : empire_agent.log atteint 790 MB en 95h, soit un 
rythme estimé à ~6 GB/mois. Pas de fuite mémoire détectée, mais la 
croissance n'est pas tenable. À implémenter via RotatingFileHandler 
Python ou logrotate Windows.
**Priorité** : P3
**Condition de déclenchement** : à planifier avant que le disque 
n'atteigne un seuil critique. Inutilement urgent pour l'instant.

### 8. Harmonisation format log [RISK] vs [RISK_CAP]

**Description** : Le brief Tâche 0 demandait des logs [RISK] mais 
l'implémentation a produit [RISK_CAP] avec un format mode=X 
point_val=Y au lieu du via X attendu. Le contenu informatif est 
identique, seul le format diffère. À aligner pour éviter la 
confusion documentaire future.
**Priorité** : P3
**Condition de déclenchement** : opportuniste, lors d'une prochaine 
modification de orchestrator.py.

### 9. Mise à jour header ORCHESTRATOR VERSION

**Description** : Le header au démarrage affiche toujours 
"ORCHESTRATOR VERSION: R19 — 2026-04-16" avec une liste de features 
qui ne mentionne pas BLACKLIST_OVERRIDE_WHITELIST ni le fix 
point_value du 30 avril. À mettre à jour avec une vraie versioning 
(par exemple lecture du hash git courant) ou un label R20 explicite.
**Priorité** : P3
**Condition de déclenchement** : opportuniste, à coupler avec 
toute prochaine modification de orchestrator.py.

### 10. Telegram circuit breaker au démarrage

**Description** : 10 erreurs consécutives au boot ont déclenché une 
pause de 5 minutes du bot Telegram. Probablement bénin (transient 
réseau ou nettoyage webhook initial), mais à investiguer si 
récurrent. Pas d'impact sur le trading.
**Priorité** : P3
**Condition de déclenchement** : à investiguer si l'incident se 
reproduit lors du prochain redémarrage. Sinon, fermer comme 
non-issue.

### 11. Ajout de .claude/settings.local.json au .gitignore

**Description** : Ce fichier d'état des permissions Claude Code 
pollue tous les git status futurs sans intérêt à être versionné. 
Cleanup mineur mais utile pour la lisibilité.
**Priorité** : P3
**Condition de déclenchement** : opportuniste, à inclure dans la 
prochaine modification du .gitignore.

### 12. Vérification effective des logs [RISK_CAP] sur UK100 et GER40

**Description** : Le monitoring 48h a confirmé que UK100 et GER40 
ne sont plus dans le dict d'override, mais aucune entrée [RISK_CAP] 
spécifique à ces deux symboles n'a été directement observée 
(probablement parce qu'aucune proposition n'a atteint l'étape de 
sizing pendant la fenêtre). À reconfirmer dès qu'une proposition 
shadow UK100 ou GER40 traverse les filtres jusqu'au calcul de lot.
**Priorité** : P2
**Condition de déclenchement** : surveillance continue, à valider 
avant la promotion éventuelle de UK100 ou GER40 en exécution réelle 
post-Directive 12.

---

**Synthèse priorités**

- **P1** (à traiter en Phase 3 dès J+14) : sujets 2, 3, 4
- **P2** (à investiguer avec données suffisantes) : sujets 1, 5, 6, 12
- **P3** (cleanup opportuniste) : sujets 7, 8, 9, 10, 11

**Fin du backlog. Document à actualiser après Directive 12.**

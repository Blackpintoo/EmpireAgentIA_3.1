# Prompt Claude Code — Monitoring post-redémarrage

Copie-colle le bloc ci-dessous dans Claude Code après avoir redémarré le bot :

---

```
Le bot EmpireAgentIA v3 vient d'être redémarré après les corrections (timeout 45s, hard filters 2.5/3, cooldowns réduits, etc.). Analyse les logs récents pour vérifier que tout fonctionne.

## ÉTAPE 1 : Lire les derniers logs

Lis les 200 dernières lignes du fichier de log le plus récent :
- Cherche dans le dossier `logs/` le fichier le plus récent
- Si pas de dossier logs, cherche la sortie console ou tout fichier .log à la racine

## ÉTAPE 2 : Vérifier ces 7 points critiques

Pour chaque point, indique ✅ OK ou ❌ PROBLÈME avec détails :

1. **Agents ne timeout plus** : Chercher les messages `[AGENT] ... timeout` — il ne devrait plus y en avoir (ou très rarement). Si des agents timeout encore, noter lesquels.

2. **Scores > 0** : Chercher les messages de score/confluence. Les valeurs ne doivent plus être systématiquement 0.00. Exemple attendu : `score=X.XX` avec X > 0.

3. **Propositions de trades** : Chercher `PROPOSAL`, `LONG`, `SHORT`, `NEW_TRADE`, `EXECUTE` — au moins quelques propositions doivent apparaître.

4. **Hard filters passent** : Chercher `[HARD_FILTER]` — il devrait y avoir des `PASS` et pas uniquement des `REJET`.

5. **Telegram stabilisé** : Chercher `TelegramNetworkError` ou `circuit-breaker` — les erreurs Telegram ne doivent plus boucler indéfiniment.

6. **Position Manager actif** : Chercher `[PM]` ou `manage_open_positions` — doit tourner normalement toutes les 20s.

7. **Pas d'erreur critique** : Chercher `ERROR`, `CRITICAL`, `Exception`, `Traceback` — signaler tout problème nouveau.

## ÉTAPE 3 : Rapport de santé

Produis un rapport concis avec :
- Statut global : 🟢 OPÉRATIONNEL / 🟡 PARTIEL / 🔴 BLOQUÉ
- Nombre d'agents qui répondent vs timeout par symbole
- Score moyen observé
- Nombre de propositions de trades générées
- Nombre de trades effectivement ouverts
- Erreurs restantes à corriger

## ÉTAPE 4 : Si des problèmes persistent

Si des agents timeout encore :
- Identifie lesquels et sur quels symboles
- Vérifie que MT5 est connecté : chercher les messages `[MT5]` dans les logs
- Si MT5 n'est pas connecté, c'est la cause — le signaler

Si les scores sont > 0 mais aucun trade ne passe :
- Vérifier quel filtre bloque (chercher les `reasons` dans les logs de décision)
- Lister les raisons de rejet les plus fréquentes
- Proposer des ajustements spécifiques

Ne fais AUCUNE modification de code — rapport d'analyse uniquement.
```

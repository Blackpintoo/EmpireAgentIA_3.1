# ============================================================================
# CONFIGURATION DU PLANIFICATEUR DE TACHES WINDOWS
# EmpireAgentIA_3 - 2025-12-27
#
# Ce script configure deux taches planifiees:
# 1. Optimisation quotidienne a 23h00 (tous les jours)
# 2. Monitoring KPI toutes les heures
#
# Usage (en tant qu'Administrateur):
#   powershell -ExecutionPolicy Bypass -File scripts\setup_windows_scheduler.ps1
# ============================================================================

$ErrorActionPreference = "Stop"

# Configuration
$ProjectPath = "C:\EmpireAgentIA_3"
$PythonPath = "python"  # Ou chemin complet: "C:\Python311\python.exe"
$LogPath = "$ProjectPath\logs"

# Creer le dossier logs si necessaire
if (-not (Test-Path $LogPath)) {
    New-Item -ItemType Directory -Path $LogPath -Force | Out-Null
    Write-Host "[OK] Dossier logs cree: $LogPath" -ForegroundColor Green
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  CONFIGURATION PLANIFICATEUR DE TACHES - EmpireAgentIA_3" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ============================================================================
# TACHE 1: Optimisation quotidienne a 23h00
# ============================================================================

Write-Host "[1/2] Configuration de l'optimisation quotidienne (23h00)..." -ForegroundColor Yellow

$TaskName1 = "EmpireAgent_WeeklyOptimizer"
$Description1 = "Optimisation Optuna des agents de trading - Execute tous les jours a 23h00"

# Supprimer la tache existante si elle existe
if (Get-ScheduledTask -TaskName $TaskName1 -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName1 -Confirm:$false
    Write-Host "     Tache existante supprimee" -ForegroundColor Gray
}

# Action: executer le script Python
$Action1 = New-ScheduledTaskAction `
    -Execute $PythonPath `
    -Argument "scripts\weekly_optimizer.py" `
    -WorkingDirectory $ProjectPath

# Declencheur: tous les jours a 23h00
$Trigger1 = New-ScheduledTaskTrigger -Daily -At "23:00"

# Parametres: executer meme si l'utilisateur n'est pas connecte
$Settings1 = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4)

# Creer la tache
Register-ScheduledTask `
    -TaskName $TaskName1 `
    -Description $Description1 `
    -Action $Action1 `
    -Trigger $Trigger1 `
    -Settings $Settings1 `
    -RunLevel Highest | Out-Null

Write-Host "     [OK] Tache '$TaskName1' creee" -ForegroundColor Green
Write-Host "     Frequence: Tous les jours a 23h00" -ForegroundColor Gray
Write-Host ""

# ============================================================================
# TACHE 2: Monitoring KPI toutes les heures
# ============================================================================

Write-Host "[2/2] Configuration du monitoring KPI (toutes les heures)..." -ForegroundColor Yellow

$TaskName2 = "EmpireAgent_KPIMonitor"
$Description2 = "Monitoring des KPIs avec alertes Telegram - Execute toutes les heures"

# Supprimer la tache existante si elle existe
if (Get-ScheduledTask -TaskName $TaskName2 -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName2 -Confirm:$false
    Write-Host "     Tache existante supprimee" -ForegroundColor Gray
}

# Action: executer le script Python en mode cron
$Action2 = New-ScheduledTaskAction `
    -Execute $PythonPath `
    -Argument "scripts\monitor_kpis.py --cron" `
    -WorkingDirectory $ProjectPath

# Declencheur: toutes les heures (on cree un trigger qui se repete)
$Trigger2 = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration (New-TimeSpan -Days 365)

# Parametres
$Settings2 = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

# Creer la tache
Register-ScheduledTask `
    -TaskName $TaskName2 `
    -Description $Description2 `
    -Action $Action2 `
    -Trigger $Trigger2 `
    -Settings $Settings2 `
    -RunLevel Highest | Out-Null

Write-Host "     [OK] Tache '$TaskName2' creee" -ForegroundColor Green
Write-Host "     Frequence: Toutes les heures" -ForegroundColor Gray
Write-Host ""

# ============================================================================
# RESUME
# ============================================================================

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  CONFIGURATION TERMINEE" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Taches planifiees:" -ForegroundColor White
Write-Host "  1. $TaskName1" -ForegroundColor Green
Write-Host "     -> Tous les jours a 23h00" -ForegroundColor Gray
Write-Host "     -> Optimise les agents avec Optuna" -ForegroundColor Gray
Write-Host ""
Write-Host "  2. $TaskName2" -ForegroundColor Green
Write-Host "     -> Toutes les heures" -ForegroundColor Gray
Write-Host "     -> Verifie les KPIs et envoie alertes Telegram" -ForegroundColor Gray
Write-Host ""
Write-Host "Pour verifier les taches:" -ForegroundColor Yellow
Write-Host "  Get-ScheduledTask -TaskName 'EmpireAgent_*'" -ForegroundColor Gray
Write-Host ""
Write-Host "Pour supprimer les taches:" -ForegroundColor Yellow
Write-Host "  Unregister-ScheduledTask -TaskName 'EmpireAgent_WeeklyOptimizer'" -ForegroundColor Gray
Write-Host "  Unregister-ScheduledTask -TaskName 'EmpireAgent_KPIMonitor'" -ForegroundColor Gray
Write-Host ""
Write-Host "Les logs seront dans: $LogPath" -ForegroundColor Cyan

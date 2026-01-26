# ============================================================================
# SUPPRESSION DES TACHES PLANIFIEES WINDOWS
# EmpireAgentIA_3 - 2025-12-27
#
# Usage (en tant qu'Administrateur):
#   powershell -ExecutionPolicy Bypass -File scripts\remove_windows_scheduler.ps1
# ============================================================================

Write-Host "Suppression des taches planifiees EmpireAgent..." -ForegroundColor Yellow
Write-Host ""

$Tasks = @("EmpireAgent_WeeklyOptimizer", "EmpireAgent_KPIMonitor")

foreach ($TaskName in $Tasks) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "[OK] Tache '$TaskName' supprimee" -ForegroundColor Green
    } else {
        Write-Host "[--] Tache '$TaskName' non trouvee" -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "Termine." -ForegroundColor Cyan

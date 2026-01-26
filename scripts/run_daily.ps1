Set-Location "C:\EmpireAgentIA_3"
python scripts\export_report_history.py --days 60 --output reports\ReportHistory-10960352.xlsx
python scripts\update_news_calendar.py --sources this,next --output data\news_calendar.csv
python scripts\daily_guard.py --history reports\ReportHistory-10960352.xlsx --target 167 --stop -250
python scripts\daily_performance_tracker.py --reports-dir reports --days 7 --export-dir reports\daily_exports
python scripts\purge_reports.py --source reports\daily_exports --archive reports\archive_exports --retention-days 14 --interval-days 14

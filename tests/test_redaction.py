import logging, os, sys, io
THIS_DIR = os.path.dirname(__file__); PROJECT_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
if PROJECT_ROOT not in sys.path: sys.path.insert(0, PROJECT_ROOT)

os.environ["TELEGRAM_BOT_TOKEN"] = "123456789:ABCdefGHI_jklMNOPqrstuvWX"
from utils.logger import logger

def test_redaction_masks_secrets(capsys):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    logger.error(f"token={token}")
    captured = capsys.readouterr().out
    assert token not in captured and "****" in captured

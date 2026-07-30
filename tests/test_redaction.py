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


# FIX 2026-07-30 (P1): regression — le formateur ne doit pas convertir les
# arguments numeriques en chaines, sinon toute ligne de log utilisant %d ou
# %.2f leve TypeError et le message est perdu.
def test_arguments_numeriques_preserves(capsys):
    logger.error("valeurs %.2f%% et %d et %s", -2.1, 7, "texte")
    captured = capsys.readouterr().out
    assert "valeurs -2.10% et 7 et texte" in captured
    assert "Logging error" not in captured


def test_redaction_appliquee_aux_arguments(capsys):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    logger.error("essai %s valeur=%d", token, 42)
    captured = capsys.readouterr().out
    assert token not in captured
    assert "****" in captured
    assert "valeur=42" in captured

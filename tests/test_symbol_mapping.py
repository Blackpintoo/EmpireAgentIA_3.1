from utils.mt5_client import MT5Client


def test_resolve_symbol_name_identite():
    """FIX 2026-07-30 (P1): le test attendait LINKUSD -> LNKUSD. Le symbole
    LNKUSD a été retiré du projet (aucune occurrence dans le code ni la config),
    le test portait donc sur un mapping disparu. On vérifie désormais le
    comportement réel : sans mapping déclaré, le nom est renvoyé tel quel."""
    c = MT5Client()
    assert c.resolve_symbol_name("BTCUSD") == "BTCUSD"
    assert c.resolve_symbol_name("NAS100") == "NAS100"


def test_resolve_symbol_name_inconnu_ne_leve_pas():
    c = MT5Client()
    assert isinstance(c.resolve_symbol_name("SYMBOLE_INEXISTANT"), str)

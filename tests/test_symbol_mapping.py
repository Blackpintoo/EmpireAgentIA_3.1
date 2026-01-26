from utils.mt5_client import MT5Client
def test_link_mapping():
    c = MT5Client()
    assert c.resolve_symbol_name("LINKUSD") == "LNKUSD"

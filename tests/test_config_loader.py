from config_loader import load_dotenv_env, get_required # type: ignore
import os, textwrap, tempfile, pathlib

def test_env_parsing_and_expansion(tmp_path: pathlib.Path, monkeypatch):
    # .env de base
    base = tmp_path / ".env"
    base.write_text(textwrap.dedent("""
        export MT5_LOGIN=10960352
        MT5_PASSWORD="X9bV&%2Q # not a comment"
        MT5_SERVER=VantageInternational-Demo
        FOO_NUM=42
        FLAG=true
        URL=https://api?token=${TOKEN}
    """).strip(), encoding="utf-8")
    # .env.local qui override
    local = tmp_path / ".env.local"
    local.write_text('TOKEN=abc123\nURL="https://x/${TOKEN}"\n', encoding="utf-8")

    # seed os.environ
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:abcdef")
    env = load_dotenv_env(str(base), extra_paths=[str(local)], overwrite=False)

    # types
    assert isinstance(env["FOO_NUM"], int) and env["FOO_NUM"] == 42
    assert env["FLAG"] is True
    # quotes + # not comment
    assert os.environ["MT5_PASSWORD"] == 'X9bV&%2Q # not a comment'
    # expansion + override local
    assert os.environ["URL"] == "https://x/abc123"
    # required
    d = get_required("MT5_LOGIN","MT5_SERVER","TELEGRAM_BOT_TOKEN")
    assert d["MT5_LOGIN"] == "10960352"

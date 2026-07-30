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
    # FIX 2026-07-30 (P1): load_dotenv_env est appelé avec overwrite=False, donc
    # une variable déjà présente dans l'environnement gagne. Sans ce nettoyage,
    # le test dépend de la machine et échoue si MT5_PASSWORD est déjà défini.
    for _k in ("MT5_PASSWORD", "MT5_SERVER", "MT5_LOGIN", "FOO_NUM", "FLAG", "URL", "TOKEN"):
        monkeypatch.delenv(_k, raising=False)
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

def test_hash_non_quote_non_tronque(tmp_path, monkeypatch):
    """Non-régression du bug qui a bloqué l'authentification MT5 (30/07/2026).

    Un # à l'intérieur d'une valeur NON quotée ne doit pas être traité comme
    un commentaire. Seul le cas quoté était couvert jusqu'ici ; c'est
    précisément la forme non quotée qui tronquait le mot de passe à 3
    caractères et provoquait un `-6 Authorization failed` inexplicable.
    """
    from utils.config_loader import _strip_inline_comment

    # dans une valeur : conservé
    assert _strip_inline_comment("fw7#PXZ5") == "fw7#PXZ5"
    assert _strip_inline_comment("abc#def#ghi") == "abc#def#ghi"
    # précédé d'un espace : vrai commentaire
    assert _strip_inline_comment("valeur # commentaire") == "valeur"
    assert _strip_inline_comment("valeur\t# commentaire") == "valeur"
    # en début de valeur : commentaire
    assert _strip_inline_comment("# tout est commentaire") == ""
    # quoté : inchangé
    assert _strip_inline_comment('"fw7#PXZ5"') == '"fw7#PXZ5"'

    # bout en bout via le fichier .env
    env = tmp_path / ".env"
    env.write_text("MT5_PASSWORD=fw7#PXZ5\nAUTRE=valeur # ceci est un commentaire\n",
                   encoding="utf-8")
    monkeypatch.delenv("MT5_PASSWORD", raising=False)
    monkeypatch.delenv("AUTRE", raising=False)
    from config_loader import load_dotenv_env  # type: ignore
    out = load_dotenv_env(str(env), overwrite=True)
    assert out["MT5_PASSWORD"] == "fw7#PXZ5", "le # dans la valeur a ete tronque"
    assert out["AUTRE"] == "valeur"

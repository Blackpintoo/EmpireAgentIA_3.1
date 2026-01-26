from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, Iterable
import os
import re

_ASSIGN_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")
_QUOTE_RE  = re.compile(r'^([\'"])(.*)\1$')
_EXPAND_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

def _coerce(val: str) -> Any:
    """Essaye de typer les valeurs usuelles pour le dict retourné (pas pour os.environ)."""
    s = val.strip()
    sl = s.lower()
    if sl in ("true", "false"):
        return sl == "true"
    # int
    if re.fullmatch(r"[+-]?\d+", s):
        try: return int(s)
        except Exception: pass
    # float
    if re.fullmatch(r"[+-]?\d+\.\d+", s):
        try: return float(s)
        except Exception: pass
    return s

def _strip_inline_comment(raw: str) -> str:
    """Retire les commentaires inline non quotés (ex: KEY=abc # comment)."""
    # si quoted, on ne touche pas
    if _QUOTE_RE.match(raw.strip()):
        return raw.strip()
    # sinon on coupe au premier # non échappé
    out = []
    escaped = False
    for ch in raw:
        if ch == "#" and not escaped:
            break
        escaped = (ch == "\\" and not escaped)
        out.append(ch)
    return "".join(out).strip()

def _unquote(val: str) -> str:
    m = _QUOTE_RE.match(val.strip())
    if not m:
        return val.strip()
    quote, inner = m.group(1), m.group(2)
    # unescape simple pour les guillemets doubles
    if quote == '"':
        inner = inner.replace(r"\\", "\\").replace(r"\"","\"").replace(r"\n","\n").replace(r"\r","\r").replace(r"\t","\t")
    return inner
def _expand(val: str, env_chain: Dict[str, str]) -> str:
    """Expand ${VAR} depuis os.environ puis env_chain (ordre de priorité)."""
    def repl(m):
        k = m.group(1)
        return os.environ.get(k) or env_chain.get(k, "")
    return _EXPAND_RE.sub(repl, val)

def _parse_env_lines(lines: Iterable[str], base: Dict[str, str]) -> Dict[str, str]:
    """Parse des lignes .env et retourne un dict (str->str)."""
    acc: Dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _ASSIGN_RE.match(line)
        if not m:
            continue
        key, rhs = m.group(1), m.group(2)
        rhs = _strip_inline_comment(rhs)
        rhs = _unquote(rhs)
        rhs = _expand(rhs, {**base, **acc})  # permet références à des clés précédentes
        acc[key] = rhs
    return acc

def load_dotenv_env(path: str | None = "config/.env",
                    extra_paths: Iterable[str] | None = ("config/.env.local",),
                    overwrite: bool = False) -> Dict[str, Any]:
    """
    Charge .env/.env.local sans dépendre de python-dotenv.
    Priorité (de la plus forte à la plus faible): os.environ > extra_paths > path.
    - overwrite=False: n'écrase jamais os.environ (par défaut – recommandé en prod/CI)
    - Retourne un dict 'typé' (bool/int/float/str) utile côté Python, mais
      n'injecte QUE des str dans os.environ (comportement standard).
    """
    all_env_raw: Dict[str, str] = {}
    paths: Iterable[str] = []
    if path:
        paths = [path]
    if extra_paths:
        paths = list(paths) + list(extra_paths)

    # Empilement: on lit d'abord le fichier "faible priorité", puis override avec suivants
    for pth in paths:
        p = Path(pth)
        if not p.exists():
            continue
        lines = p.read_text(encoding="utf-8").splitlines()
        parsed = _parse_env_lines(lines, base=all_env_raw)
        all_env_raw.update(parsed)

    # Injection dans os.environ
    for k, v in all_env_raw.items():
        if overwrite:
            os.environ[k] = v
        else:
            os.environ.setdefault(k, v)

    # Dict "typé" à renvoyer (utile pour du code Python)
    typed: Dict[str, Any] = {k: _coerce(v) for k, v in all_env_raw.items()}
    return typed

def get_required(*keys: str) -> Dict[str, str]:
    """Récupère une liste de clés obligatoires depuis os.environ, lève une erreur lisible si manquantes."""
    missing = [k for k in keys if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"Variables d'environnement manquantes: {', '.join(missing)}")
    return {k: os.environ[k] for k in keys}
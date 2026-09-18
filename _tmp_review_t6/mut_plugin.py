"""External mutation probe for T6 review (loaded via -p). Deleted after use."""
import os
import re

import pytest

_MUT = os.environ.get("QWENPAW_MUT", "")


@pytest.fixture(autouse=True)
def _apply_mutation():
    if _MUT == "hash":
        from qwenpaw.app.kb import ingest
        ingest.content_hash = lambda _s: "deadbeef"
    elif _MUT == "fence":
        from qwenpaw.app.kb import links
        links._FENCE_RE = re.compile(r"^\x00NEVERMATCH")
    elif _MUT == "rrf1":
        from qwenpaw.app.kb import pg_engine as pe
        pe._VEC_CTE = pe._VEC_CTE.replace(" - 1 AS rank", " AS rank")
        pe._KW_CTE = pe._KW_CTE.replace(" - 1 AS rank", " AS rank")
    yield

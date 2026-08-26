#!/usr/bin/env bash
# End-to-end smoke against a freshly generated fixture repo, using only the
# installed `buzz` CLI and git. Catches undeclared runtime dependencies and
# any break in the analyze -> play -> answer -> atlas/recap loop.
set -euo pipefail

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
repo="$work/fixture"
mkdir -p "$repo/pkg/extras"

cat > "$repo/pkg/__init__.py" <<'EOF'
"""Fixture package."""
from .core import Core
EOF
cat > "$repo/pkg/core.py" <<'EOF'
"""Core orchestration."""
from .base import Base
from .util import helper

def show():
    from .render import draw  # lazy: render imports core at top level
    return draw
EOF
echo 'from .core import Core
from .base import Base' > "$repo/pkg/render.py"
echo 'import os' > "$repo/pkg/base.py"
echo 'from .base import Base' > "$repo/pkg/util.py"
echo 'from .core import Core
from .base import Base' > "$repo/pkg/table.py"
echo 'from .base import Base
from .util import helper' > "$repo/pkg/text.py"
echo 'from ..text import Base' > "$repo/pkg/extras/fmt.py"
echo 'from .table import Core' > "$repo/pkg/demo.py"

git -C "$repo" init -q
G="git -C $repo -c user.email=ci@ci -c user.name=ci"
$G add . && $G commit -qm "init"
for i in 1 2 3; do
  echo "# rev $i" >> "$repo/pkg/base.py"
  echo "# rev $i" >> "$repo/pkg/demo.py"
  $G commit -qam "FIX keep base and demo in step ($i)"
done

game="$work/game"
mkdir -p "$game" && cd "$game"
buzz analyze "$repo"
BUZZ_SESSION=ci buzz play > /dev/null
BUZZ_SESSION=ci buzz look > /dev/null
BUZZ_SESSION=ci buzz map > /dev/null
BUZZ_SESSION=ci buzz quests > /dev/null
qid="$(BUZZ_SESSION=ci buzz quests all | awk '/cycle/ {print $1; exit}')"
if [ -n "$qid" ]; then
  BUZZ_SESSION=ci buzz answer "$qid" walk render core | grep -q CORRECT
fi
BUZZ_SESSION=ci buzz atlas > /dev/null
BUZZ_SESSION=ci buzz recap > /dev/null
test -s .buzz/atlas.html && test -s .buzz/field_notes.md
echo "smoke OK"

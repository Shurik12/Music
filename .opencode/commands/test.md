---
description: Проверить синтаксис и импорты (без запуска live-команд)
---

Проверь, что проект собирается и импорты в порядке:

```bash
cd ~/Music
uv sync
uv run python -c "
from src.cli import CLI
from src import color, paths, track
from src.yamusic import YaMusicHandle
from src.ytmusic import YTMusicClient
from src.buildin import BuildinClient
from src.buildin_maps import export_maps, import_maps
from src.logger import setup_logging
from src.args import parse_args
print('All imports OK')
"
```

Отчитайся: что импортировалось, что упало и почему. Упавшее не «чинить молча» — сначала покажи причину и дождись решения.

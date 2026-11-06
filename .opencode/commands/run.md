---
description: Запустить CLI в интерактивном режиме (uv run main.py)
---

Запусти Music CLI:

```bash
cd ~/Music && uv run main.py
```

Меню — curses (стрелки ↑/↓, Enter — выбрать, q/esc — назад/выход, 1-N — быстрый выбор). После каждой команды — «Press Enter to continue...». Лог — только в `logs/music_api_<ts>.log`, в консоль не пишется.

Для smoke-теста: запусти, выбери любой mode, нажми `q` для выхода. Команды, которые трогать live-аккаунты (Yandex API, YouTube Music), выполнять только с явного согласия пользователя.

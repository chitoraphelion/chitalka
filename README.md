# chitalka

Читалка PDF-статьи на LaTeX: выделяете фрагмент, пишете, что исправить, —
ИИ-агент видит комментарии, правит `.tex`, отвечает в той же карточке.

## Установка

```sh
uv tool install -e ~/code/python/chitalka     # команда chitalka появится в ~/.local/bin
```

Без установки: `python3 -m chitalka` из папки репозитория (`PYTHONPATH=~/code/python/chitalka`).
Зависимостей нет, нужен Python ≥ 3.10; pdf.js 3.11 лежит в `chitalka/static/vendor`.

## Запуск

Проект устроен так: `main.tex` в корне, PDF — `./main.pdf` или `./build/main.pdf`.

```sh
cd ~/path/to/paper
chitalka                    # ./main.pdf, иначе ./build/main.pdf
chitalka build/paper.pdf    # другой PDF
chitalka --no-browser -p 9000
```

Комментарии: `./kommentarii/kommentarii.json` (в старых проектах — `./notes/kommentarii.json`),
рядом — `HOW_TO_USE_CHITALKA.md`, памятка для агентов. Несколько проектов можно открыть
одновременно: каждый займёт свой порт; повторный запуск в той же папке откроет уже работающую читалку.

Для точных строк собирайте с SyncTeX: `latexmk -synctex=1 …` (или `$synctex = 1;` в `.latexmkrc`).
Тогда у комментария будет `source: main.tex:397-403 (synctex)`, иначе — поиск по словам.

## Команды для агентов

```sh
chitalka list               # открытые, ждущие ответа (--all, --done, --json)
chitalka show ID
chitalka reply ID "что сделано" [--done]
chitalka done ID [ID ...] [-m "текст"]
chitalka reopen ID
chitalka init | where
```

## В читалке

- клик по ссылке (литература, формула, теорема, раздел) — переход, `Alt+←` или `←` в шапке — назад;
  наведение — предпросмотр места назначения;
- выделение формул подсвечивается сплошными блоками; `C` — комментарий, `1`–`5` — с категорией;
- `D` — тема (авто/светлая/тёмная), `I` — тёмные страницы; шрифт интерфейса — `font_family`
  из `~/.config/kitty/kitty.conf` (или `--font "Имя шрифта"`); `?` — все клавиши.

## Тесты

```sh
uv run --with pytest pytest -q
```

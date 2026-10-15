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
chitalka --watch            # + latexmk -pvc, автообновление
chitalka --no-browser -p 9000
```

Комментарии: `./kommentarii/kommentarii.json` (в старых проектах — `./notes/kommentarii.json`),
рядом — `HOW_TO_USE_CHITALKA.md`, памятка для агентов. Несколько проектов можно открыть
одновременно: каждый займёт свой порт; повторный запуск в той же папке откроет уже работающую читалку.

`chitalka --watch` сам запускает `latexmk -pvc -synctex=1` (движок — из `.latexmkrc`,
подсказки `xelatex` в начале `main.tex` или `--engine`), новые сборки загружаются без `R`,
ошибка сборки видна в шапке, клик по ней открывает nvim на строке ошибки. Лог — `kommentarii/latexmk.log`.

Кнопка `✎ файл:строка` на карточке (или `E`) открывает место в nvim: новой вкладкой в окне kitty,
где запущена читалка (`allow_remote_control yes`), иначе новым окном kitty.
Своя команда: `--editor "code -g {file}:{line}"` или `$CHITALKA_EDITOR`.

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
- масштаб: щипок двумя пальцами на тачпаде (или `Ctrl`+колесо) вокруг точки под пальцами, `+`/`−`, `W` — по ширине;
- выделение формул подсвечивается сплошными блоками; `C` — комментарий, `1`–`5` — с категорией;
- `D` — тема: тёплая светлая ↔ тёмная, `I` — тёмные страницы; `H` — скрыть шапку,
  `]` — комментарии, `[` — оглавление, `F` — режим чтения (скрыть всё и вернуть как было); шрифт интерфейса — `font_family`
  из `~/.config/kitty/kitty.conf` (или `--font "Имя шрифта"`); `?` — все клавиши.

## Тесты

```sh
uv run --with pytest pytest -q
```

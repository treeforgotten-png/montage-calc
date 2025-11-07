
# Калькулятор стоимости выезда — сборка (Яндекс.Карты + подсказки)

Готовая статическая страница `index.html`.
Работает **только по http/https**, фирменные подсказки Яндекса не работают из `file://`.

## Быстрый тест на Netlify (без Git)
1. Открой https://app.netlify.com/drop
2. Перетащи сюда файл `montage-calc.zip` (или распакованную папку)
3. Получишь ссылку вида `https://*.netlify.app` — можно отдавать коллегам

## GitHub Pages
1. Создай репозиторий, залей `index.html`
2. Settings → Pages → Deploy from branch → main/(root)
3. Ссылка: `https://<user>.github.io/<repo>/`

## Настройка ключа Яндекса
В консоли API добавь разрешённые источники (Referrers):
- `https://*.github.io`
- `https://*.netlify.app`
- твой прод-домен

Ключ вшит в `index.html` как предоставлял пользователь.

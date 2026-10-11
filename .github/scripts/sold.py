"""Отмечает выкупленные лоты на сайте без пересборки страницы.

Читает комментарии к посту-архиву в Telegram (тот же публичный виджет, что
build_telegram.py) и у фото, под которыми канал написал «Выкуплен», ставит
"sold": true в window.TG_PHOTOS страниц index.html и test/index.html; снимает
пометку, если подпись убрали. Новые фото не добавляет — это делается вручную.
Запускается по расписанию GitHub Actions (.github/workflows/sold.yml).
"""
import html, json, re, sys, time, urllib.parse, urllib.request

PAGES = ['index.html', 'test/index.html']
UA = {'User-Agent': 'Mozilla/5.0'}


def fetch(url, data=None):
    for attempt in range(8):
        try:
            hdr = dict(UA, **({'X-Requested-With': 'XMLHttpRequest'} if data else {}))
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=hdr), timeout=30) as res:
                return res.read().decode('utf-8')
        except OSError as e:
            print('  повтор %d: %s' % (attempt + 1, e))
            time.sleep(5)
    sys.exit('Telegram не отвечает: ' + url)


def parse(page):
    """[(id сообщения, автор, число фото, текст)]"""
    out = []
    for b in re.split(r'(?=<div class="tgme_widget_message )', page)[1:]:
        mid = re.search(r'data-post-id="(\d+)"', b)
        if not mid:
            continue
        author = re.search(r'tgme_widget_message_author_name[^>]*>(.*?)</', b, re.S)
        text = re.search(r'class="tgme_widget_message_text[^>]*>(.*?)</div>', b, re.S)
        out.append((int(mid.group(1)),
                    html.unescape(re.sub('<[^>]+>', '', author.group(1))).strip() if author else '',
                    len(re.findall('tgme_widget_message_photo_wrap', b)),
                    html.unescape(re.sub('<[^>]+>', ' ', text.group(1))) if text else ''))
    return out


def sold_names(post):
    page = fetch(post.split('?')[0] + '?embed=1&discussion=1&comments_limit=100')
    form = {k: re.search(r'name="%s" value="([^"]+)"' % k, page) for k in ('peer', 'top_msg_id', 'discussion_hash')}
    api = re.search(r'"api_url":"([^"]+)"', page)
    if not api or not all(form.values()):
        sys.exit('Не нашёл комментарии к посту (Telegram поменял виджет?)')
    api = api.group(1).replace('\/', '/')
    form = {k: m.group(1) for k, m in form.items()}
    msgs = parse(page)
    while msgs:
        before = min(m[0] for m in msgs)
        data = urllib.parse.urlencode(dict(form, before_id=before, method='loadComments')).encode()
        more = [m for m in parse(json.loads(fetch(api, data)).get('comments_html', '')) if m[0] < before]
        if not more:
            break
        msgs += more
    print('Комментариев:', len(msgs))
    counts = {}
    for _, author, n, _ in msgs:
        if n:
            counts[author] = counts.get(author, 0) + 1
    channel = max(counts, key=counts.get)
    return {'tg-%d-%d' % (mid, i) for mid, author, n, text in msgs
            if author == channel and 'выкуплен' in text.lower() for i in range(n)}


def main():
    pages = {p: open(p, encoding='utf-8').read() for p in PAGES}
    post = json.loads(re.search(r'window\.TG_POST = (.*?);\n', pages['index.html']).group(1))
    sold = sold_names(post)
    print('Выкуплено фото:', len(sold))
    for path, s in pages.items():
        m = re.search(r'window\.TG_PHOTOS = (\[.*?\]);\n', s)
        photos = json.loads(m.group(1))
        changed = []
        for p in photos:
            if (p['name'] in sold) != bool(p.get('sold')):
                changed.append(p['name'])
                if p['name'] in sold:
                    p['sold'] = True
                else:
                    p.pop('sold')
        if changed:
            s = s.replace(m.group(0), 'window.TG_PHOTOS = %s;\n' % json.dumps(photos, ensure_ascii=False), 1)
            open(path, 'w', encoding='utf-8', newline='').write(s)
        print('%s: изменено %d %s' % (path, len(changed), ' '.join(changed)))


main()

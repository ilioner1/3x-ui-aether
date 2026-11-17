# پنل 3x-ui با اوتباند Aether

این شاخه لینک‌های `aether://` را به هستهٔ واقعی Aether v2.4.0 وصل می‌کند.
پشتیبانی فعلی MASQUE روی HTTP/2 و HTTP/3 است. لینک نمونه:

```text
aether://162.159.198.223:443?protocol=masque&scan=balanced&ip=v4&transport=h2#mokhaberaat2
```

## نصب مستقل با Docker

```bash
git clone -b feat/aether-outbound https://github.com/ilioner1/3x-ui-aether.git
cd 3x-ui-aether
docker compose -f compose.aether.yml up -d --build
docker compose -f compose.aether.yml logs panel
```

پنل روی `127.0.0.1:2053` باز می‌شود. برای دسترسی از کامپیوتر خودتان از SSH forwarding استفاده کنید:

```bash
ssh -L 2053:127.0.0.1:2053 user@server
```

نام کاربری و رمز تصادفی در خروجی راه‌اندازی پنل نمایش داده می‌شود.
در بخش تنظیمات Xray، اوتباند جدید بسازید و لینک را با ابزار ورود لینک وارد کنید، یا پروتکل Aether را انتخاب و URI را وارد کنید.
ذخیره کنید و در Routing، ترافیک دلخواه را به تگ `mokhaberaat2` بفرستید.

دکمهٔ تست، درخواست HTTP واقعی را از Xray و هستهٔ Aether عبور می‌دهد. حتی در حالت TCP، تست Aether از خود تونل انجام می‌شود.
عدد نمایش‌داده‌شده تأخیر درخواست از تونل است، نه ICMP ping به IP کلادفلر.

## نصب هسته کنار بیلد سفارشی پنل

```bash
bash scripts/install-aether.sh bin
```

این اسکریپت نسخه و SHA-256 مشخص را بررسی می‌کند. در Docker این مرحله خودکار است.
برای مسیر متفاوت از `XUI_AETHER_BINARY` استفاده کنید. داده‌های هویت زیر پوشهٔ `aether` کنار دیتابیس پنل، و لاگ هر هسته در `core.log` همان پوشه نگهداری می‌شوند.

پارامترهای قابل ورود: `protocol=masque`، `transport=h2|h3`، `scan=turbo|balanced|thorough|stealth|ironclad`، `ip=v4|v6|both` و `noize=off|light|firewall|balanced|gfw|aggressive`.
وقتی IP و پورت در لینک مشخص‌اند، `--peer` به هسته داده می‌شود و اسکن اولیه لازم نیست.

هر اوتباند یک پردازش و پورت SOCKS5 روی loopback دارد. توقف پنل، حذف اوتباند و پایان تست، پردازش مربوط را می‌بندد.
در برخورد نادر پورت تولیدشده با سرویس دیگر، خطا اعلام می‌شود؛ تغییر تگ اوتباند، پورت دیگری تولید می‌کند.
اتصال این IP روی شبکه یا کشور دیگر باید جداگانه تست شود. اتصال روی یک runner تضمین اتصال روی سرور شما نیست.

کد پنل تحت GPL-3.0 و هستهٔ مجزای Aether تحت AGPL-3.0-only است.
سورس هسته: https://github.com/CluvexStudio/Aether/tree/v2.4.0

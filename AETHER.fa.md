# پنل 3x-ui با اوتباند Aether

این شاخه لینک‌های `aether://` را به هستهٔ واقعی Aether v2.4.0 وصل می‌کند.
پشتیبانی فعلی MASQUE روی HTTP/2 و HTTP/3 است و می‌توان Psiphon را به‌عنوان خروجی پس از MASQUE انتخاب کرد. لینک نمونه:

```text
aether://162.159.198.223:443?protocol=masque&scan=balanced&ip=v4&transport=h2#mokhaberaat2
```

نمونهٔ زنجیرهٔ Psiphon با درخواست خروجی هند:

```text
aether://162.159.199.111:1701?protocol=masque&scan=thorough&ip=v4&transport=h2&psiphon=chain&psiphon_mode=auto&region=IN#mokhaberaat
```

پارامتر `psiphon=chain` ترافیک را از MASQUE به Psiphon می‌فرستد. `psiphon_mode` یکی از `auto`، `cdn` و `direct` است. `region` کد دوحرفی منطقهٔ درخواستی است و اتصال به موجود بودن خروجی آن منطقه بستگی دارد.

## نصب مستقیم مثل سنایی

روی Ubuntu، Debian یا Armbian با systemd و پردازندهٔ amd64 یا arm64، در SSH و با دسترسی root اجرا کنید:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/ilioner1/3x-ui-aether/v3.11.0-aether.5/install.sh)
```

نصب‌کننده بستهٔ آمادهٔ پنل، Xray و Aether را از همین مخزن می‌گیرد و منوی `x-ui` و سرویس `x-ui.service` را راه می‌اندازد. نصب به Docker، Go یا Node.js نیاز ندارد. برای دیدن منو `x-ui` و برای دیدن آدرس و تنظیمات پنل `x-ui settings` را اجرا کنید.

این مسیر برای نصب تازه است. اگر نصب یا پایگاه‌دادهٔ سنایی از قبل روی سرور وجود داشته باشد، نصب‌کننده متوقف می‌شود تا بتوانید قبل از مهاجرت از داده‌ها نسخهٔ پشتیبان بگیرید. به‌روزرسانی پنل از مخزن اصلی سنایی برای این نصب غیرفعال است.

## به‌روزرسانی نسخهٔ نصب‌شدهٔ Aether

روی نصب مستقیم قبلی Aether، با دسترسی root این دستور را اجرا کنید. پنل برای به‌روزرسانی پنل و نصب Psiphon کوتاه‌مدت راه‌اندازی مجدد می‌شود و پایگاه‌داده، تنظیمات و هسته‌ها حفظ می‌شوند.

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/ilioner1/3x-ui-aether/v3.11.0-aether.5/scripts/update-aether-panel.sh)
```

## ساخت کانفیگ VLESS با خروجی Aether

1. در **Xray Configs → Outbounds** روی افزودن اوتباند بزنید و لینک `aether://` را در ورودی **Import** بالای فرم بچسبانید. می‌توانید همان لینک را از **More → Import Outbounds** هم وارد کنید. پنل پروتکل **Aether** و تگ `mokhaberaat2` را از لینک نمونه می‌خواند. اوتباند را به فهرست اضافه کنید.
2. در **Inbounds** یک اینباند **VLESS** بسازید و برای آن یک کلاینت فعال کنید. تگ اینباند را یادداشت کنید.
3. در **Xray Configs → Routing** یک قانون بسازید. در **Inbound Tag** تگ اینباند VLESS و در **Outbound Tag** تگ `mokhaberaat2` را انتخاب کنید. قانون را بالاتر از قانون‌های عمومی‌ای بگذارید که می‌توانند همین ترافیک را بگیرند. تنظیمات Xray را ذخیره کنید.
4. در **Inbounds** لینک اشتراک‌گذاری `vless://` همان کلاینت را کپی و در برنامهٔ کلاینت وارد کنید. کلاینت به آدرس و پورت اینباند روی سرور شما وصل می‌شود و Xray ترافیک آن را به Aether می‌فرستد.

دکمهٔ تست اوتباند زمان یک درخواست واقعی HTTP از طریق تونل Aether را بر حسب میلی‌ثانیه نشان می‌دهد.

## نصب هسته کنار بیلد سفارشی پنل

```bash
bash scripts/install-aether.sh bin
```

این اسکریپت نسخه و SHA-256 مشخص را بررسی می‌کند.
برای مسیر متفاوت از `XUI_AETHER_BINARY` استفاده کنید. داده‌های هویت زیر پوشهٔ `aether` کنار دیتابیس پنل، و لاگ هر هسته در `core.log` همان پوشه نگهداری می‌شوند.

پارامترهای قابل ورود: `protocol=masque`، `transport=h2|h3`، `scan=turbo|balanced|thorough|stealth|ironclad`، `ip=v4|v6|both` و `noize=off|light|firewall|balanced|gfw|aggressive`.
وقتی IP و پورت در لینک مشخص‌اند، `--peer` به هسته داده می‌شود و اسکن اولیه لازم نیست.

هر اوتباند یک پردازش و پورت SOCKS5 روی loopback دارد. توقف پنل، حذف اوتباند و پایان تست، پردازش مربوط را می‌بندد.
اگر پورت پیشنهادی اشغال باشد، پنل یک پورت آزاد برای اوتباند جدید انتخاب می‌کند.
اتصال این IP روی شبکه یا کشور دیگر باید جداگانه تست شود. اتصال روی یک runner تضمین اتصال روی سرور شما نیست.

کد پنل تحت GPL-3.0 و هستهٔ مجزای Aether تحت AGPL-3.0-only است.
سورس هسته: https://github.com/CluvexStudio/Aether/tree/v2.4.0

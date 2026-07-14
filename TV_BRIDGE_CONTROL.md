# 🌉 لوحة تحكّم جسر TradingView → MT5

آخر تفعيل: 2026-07-13 · ماجيك `20260710` · ديمو فقط (Exness Trial)

## الرابط العام (Webhook)

```
https://nano-bias-ray-beach.trycloudflare.com/tv
```

> النطاق مجاني ويتغيّر عند كل إعادة تشغيل للنفق. الرابط الحيّ الأحدث دائماً في:
> `data/r_native/tv_tunnel.json`

## قالب رسالة تنبيه TradingView

```json
{
  "secret": "eu362aZ3SPaG5YFtMMJZWzihgJuHT3b7",
  "action": "{{strategy.order.action}}",
  "symbol": "XAUUSDm",
  "lot": 0.01
}
```

- `action`: buy / sell / close (أو long / short / flat)
- ضع الرابط أعلاه في خانة Webhook URL، والقالب في خانة Message.

## التحكّم من هنا (الجسر يقرأ هذه الملفات لحظياً — لا حاجة لإعادة تشغيل)

الملف: `data/r_native/tradingview_bridge_config.json`

| المفتاح | القيمة الحالية | الأثر |
|---------|----------------|-------|
| `execute` | `true` | `false` = تسجيل فقط بلا تنفيذ · `true` = تنفيذ فعليّ |
| `max_lot` | `0.10` | سقف حجم الصفقة |
| `default_lot` | `0.01` | الحجم إن لم يُرسله التنبيه |
| `allowed_symbols` | `[]` (الكل) | قائمة بيضاء، مثال `["XAUUSDm"]` |
| `enabled` | `true` | `false` = تعطيل الجسر كلياً |

**إيقاف طارئ فوري:** أنشئ ملفاً فارغاً باسم `kill_switch.txt` في مجلد `MT5` أو `data/r_native` — الجسر يرفض كل تنفيذ فوراً.

## ضوابط الأمان المفعّلة

ديمو فقط (يرفض أي حساب حقيقي) · سرّ إجباري في كل طلب (403 عند الخطأ) · سقف لوت 0.10 · احترام kill_switch · كل طلب يُسجَّل في `tradingview_bridge.jsonl`.

## المكوّنات وإبقاؤها حيّة

- `tradingview_bridge.py` — الجسر على `:8025/tv`
- `tv_tunnel_keeper.py` — يُبقي cloudflared حيّاً (يعيد تشغيله تلقائياً) + يحرس الجسر
- كلاهما مسجّل في `watchdog_guard.py` (الوصيّ) — عند أي إعادة تشغيل للجهاز يُعيدهما الوصيّ تلقائياً.

## إعادة التشغيل اليدوي

شغّل: `START_TV_BRIDGE_LIVE.bat` (يفحص الجسر، يشغّل النفق، يطبع الرابط، يختبر السرّين).

## آخر نتيجة اختبار (عبر الرابط العام)

- سرّ صحيح → `200` مقبول ✅
- سرّ خاطئ → `403` مرفوض ✅

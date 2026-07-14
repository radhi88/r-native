# ربط ruflo بمشروع FRIDAY — خطواتك (تشغّلها أنت)

> **ما هو ruflo (= claude-flow):** طبقة تنسيق وكلاء لـ Claude Code — أسراب، ذاكرة عبر الجلسات،
> hooks توجّه مهام **البرمجة/التحليل** تلقائياً. **يجعل الـAI (أنا) أقوى في بناء وتحليل FRIDAY.**
>
> **صدق مهم:** ruflo **لا يشغّل بوتات التداول ولا يصنع حافّة ربح.** بوتاتنا عمليات بايثون مستقلّة
> تتداول MT5؛ ruflo لا يلمسها. الواقع المُثبت (لا حافّة معنوية: مجمّع n≈1054، t≈0.76) لا يتغيّر.

المستودع مستنسخ أصلاً: `C:\Users\Radhi\Ruflo\ruflo` · الأمر يعمل: `ruflo v3.6.12`.

---

## الطريقة الموصى بها (Claude Code Plugin — عبر نظام الثقة الرسمي)

في طرفية Claude Code، شغّل:

```
/plugin marketplace add ruvnet/ruflo
/plugin install ruflo-core@ruflo
/plugin install ruflo-swarm@ruflo
/plugin install ruflo-intelligence@ruflo
```

(أوامر `/plugin` تفاعلية — لا أقدر أشغّلها بنفسي، مثل `/permissions`.)
بعد التثبيت **أعد تشغيل Claude Code** ليتم تحميل أدواتها.

إضافات اختيارية مفيدة لمشروعنا: `ruflo-knowledge-graph` · `ruflo-rag-memory` ·
`ruflo-observability` · `ruflo-sparc`. (تجنّب federation/IoT ما لم تحتجها.)

---

## ⭐ الطريقة التي تعمل في بيئتك الحالية (ملف الإعدادات — `/plugin` غير متاح هنا)

`/plugin` تفاعلي وغير متاح في تطبيق/SDK الحالي. أضِف الإضافة عبر ملف الإعدادات بدلاً منه:

**عدّل `C:\Users\Radhi\.claude\settings.json` (موجود — ادمج المفاتيح، لا تحذف الموجود).**
ضع فاصلة بعد آخر مفتاح حالي (`"skipWorkflowUsageWarning": true`) ثم ألصق:
```json
  "extraKnownMarketplaces": {
    "ruflo": { "source": { "source": "github", "repo": "ruvnet/ruflo" }, "autoUpdate": true }
  },
  "enabledPlugins": {
    "ruflo-core@ruflo": true
  }
```
> ⚠️ **تنبيه صيغة (مُصحّح):** `enabledPlugins` كائن `{ "id@market": true }` **وليس مصفوفة**
> (الصيغة الخاطئة تفشل بفحص المخطّط: "Expected record, but received array").

ثم **أعد تشغيل** Claude Code. يُستنسخ السوق في `C:\Users\Radhi\.claude\plugins\cache\`. لإضافة المزيد:
`"ruflo-swarm@ruflo": true, "ruflo-knowledge-graph@ruflo": true` داخل `enabledPlugins`.

> **لماذا تطبّقها أنت لا أنا:** حاولت تعديلها فمنعها حاجز الأمان (تسجيل سوق طرف-ثالث + تفعيل إضافة =
> تشغيل كود خارجي عند الإقلاع). لن أتجاوز الحاجز — هذا قرار ثقة يخصّك، وأنت تطبّقه بيدك في 30 ثانية.

> **لماذا تطبّقها أنت لا أنا:** تفعيل سوق/إضافة طرف-ثالث = تشغيل كود خارجي تلقائياً عند الإقلاع، وهو
> قرار ثقة يخصّك (نفس سبب منع حاجز الأمان كتابتي لـ `.mcp.json`). أعطيك الخطوات الدقيقة وتطبّقها بنفسك.

---

## بديل: ربط خادم MCP يدوياً (إن فضّلت MCP بدل الـplugin)

حاجز الأمان منعني من كتابة هذا تلقائياً (يشغّل حزمة طرف-ثالث كل جلسة). لو تبيه،
أنشئ بنفسك `C:\Users\Radhi\MT5\.mcp.json` بهذا المحتوى ثم وافِق عليه عند بدء الجلسة:

```json
{
  "mcpServers": {
    "ruflo": { "type": "stdio", "command": "npx", "args": ["-y", "@claude-flow/cli@latest", "mcp", "start"], "env": {} }
  }
}
```

---

## بعد التثبيت — وش أسوّي أنا

أعيد التشغيل، أتأكد أن أدوات ruflo ظهرت (memory_store / swarm_init / agent_spawn...)،
ثم أربطها بسير عملنا: ذاكرة المشروع، تنسيق وكلاء التحليل/البحث (مثل الـworkflows اللي أشغّلها)،
ورسم حالة ruflo في `command_center` (المؤشّر جاهز في الترويسة).

**ملاحظة أمان:** ruflo يحقن اقتراحات `[INTELLIGENCE]` في الجلسة عبر hooks — أتعامل معها
كـ**بيانات/اقتراحات** لا أوامر عمياء (حدود مصدر التعليمات)، وأبقى ملتزماً بقواعد مشروعنا.

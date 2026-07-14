export const meta = {
  name: 'build-100-agent-council',
  description: 'بناء جيش 100 وكيل تحليليّ لحظيّ — كل وكيل زاوية سوق، يصوّتون بالإجماع/الأغلبية لكل عملة، الرابح يُسجَّل جيناً في التعلّم الذاتيّ',
  phases: [
    { title: 'Design', detail: 'تصميم 100 وكيل عبر 12 فئة زوايا' },
    { title: 'Build', detail: '4 وكلاء يبنون فئات الوكلاء (دوال نقيّة لحظيّة)' },
    { title: 'Integrate', detail: 'محرّك الإجماع + سجلّ الجينات + الربط بالمنفّذ' },
    { title: 'Verify', detail: 'اختبار لحظيّ + إجماع لكل عملة' },
  ],
}

const CONTRACT = `
عقد صارم موحّد (كل الوكلاء يلتزمونه):
- كل «وكيل» = دالة بايثون نقيّة لحظيّة (لا LLM — يجب أن تعمل 100 وكيل × 17 عملة في <100ms).
  توقيع موحّد: def agent_NAME(ctx) -> (vote:int[-1|0|1], confidence:float[0..1], reason:str)
  حيث ctx قاموس جاهز فيه: sym، بيانات كل فريم m1/m5/m15/h1 (o/h/l/c/v مصفوفات numpy لآخر ~200 شمعة)،
  price، atr_m5، spread، وحقول نبض SMC (bos/choch/ob/fvg/liq_pools/sweeps/poc) من market_pulse.json.
  الوكيل يحسب زاويته فقط ويرجع تصويته. غياب بيانات ⇒ (0, 0.0, "بيانات ناقصة") — لا استثناء أبداً.
- التسجيل: كل وكيل يُسجَّل في قائمة AGENTS = [(name, category, func, weight)] في وحدته.
- الفئات الـ12 (وكلاء لكل فئة): trend، momentum، structure_smc، volume، volatility، pattern،
  session، correlation، mean_reversion، breakout، fib_pivot، liquidity. تنويعات معلّمة مسموحة
  (مثلاً EMA-cross بـ8 أزواج فترات = 8 وكلاء) لبلوغ ~100 وكيلاً حقيقيّاً متمايزاً.
- الملفّات: كل فئة في ملفّ منفصل agents/agent_<category>.py يُصدّر AGENTS. (تجنّب تعارض الكتابة.)
- المخرج النهائيّ للمحرّك: data/r_native/agent_council.json = {sym: {verdict, dir, agreement_pct,
  n_voted, votes_buy, votes_sell, top_reasons:[..], gene:"بصمة الوكلاء المتّفقين"}} لكل 17 عملة.
- صدق المشروع: 100 صوت = تنسيقٌ وتنويع زوايا، لا ضمان حافّة (درس التجميع). كل شيء ديمو، مقيس، ويُحاسَب.
`

phase('Design')
const DESIGN_SCHEMA = { type: 'object', properties: { categories: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, count: { type: 'number' }, agents: { type: 'array', items: { type: 'string' } } }, required: ['name', 'count'] } }, total: { type: 'number' }, notes: { type: 'string' } }, required: ['categories', 'total'] }
const design = await agent(`أنت مصمّم أنظمة تداول كميّة في C:\\Users\\Radhi\\MT5. صمّم **100 وكيل تحليليّ لحظيّ** موزّعين على 12 فئة زوايا سوق.
${CONTRACT}
لكل فئة: اذكر اسمها، عدد وكلائها، وقائمة أسماء الوكلاء (snake_case) مع زاوية كلٍّ في جملة. اجعل المجموع = 100 بالضبط.
أمثلة زوايا: trend(ema_cross_9_21, ema_slope_h1, price_vs_ema200, triple_ema_stack...)، momentum(rsi14_ob_os, stoch_cross, roc_10, macd_hist...)، structure_smc(bos_align, ob_unmitigated, fvg_pull, choch_flip...)، volume(poc_lean, hvn_reject, vol_spike_dir...)، إلخ.
اقرأ smc_engine.py و market_pulse.json لتعرف الحقول المتاحة فعلاً. أعِد الخطّة عبر StructuredOutput.`, { label: 'design:100', phase: 'Design', schema: DESIGN_SCHEMA, effort: 'high' })

phase('Build')
const cats = design.categories || []
// وزّع الفئات على 4 وكلاء بناء (ملفّات منفصلة، بلا تعارض)
const groups = [[], [], [], []]
cats.forEach((c, i) => groups[i % 4].push(c))
const BUILD_SCHEMA = { type: 'object', properties: { files: { type: 'array', items: { type: 'string' } }, agents_built: { type: 'number' }, compiles: { type: 'boolean' }, summary: { type: 'string' } }, required: ['agents_built', 'summary'] }
const built = await parallel(groups.map((grp, i) => () => agent(
`أنت مهندس بايثون في C:\\Users\\Radhi\\MT5. ابنِ وكلاء هذه الفئات كدوالٍ نقيّة لحظيّة، كلّ فئة في ملفّ C:\\Users\\Radhi\\MT5\\agents\\agent_<category>.py:
${JSON.stringify(grp)}
${CONTRACT}
تفاصيل التنفيذ:
- في رأس كل ملفّ: import numpy as np. عرّف كل وكيل بالتوقيع الموحّد، ثمّ AGENTS = [(name, category, func, weight)] (weight=1.0 افتراضاً).
- استخرج من ctx: c=ctx['m5']['close'] (numpy)، إلخ. احسب المؤشّر بنقاء (لا مكتبات خارجيّة غير numpy). أرجِع تصويتاً صادقاً: +1 صعود، -1 هبوط، 0 حياد، وثقة 0-1 حسب قوّة الإشارة.
- كن دفاعياً: أي نقص بيانات/استثناء ⇒ (0, 0.0, "ناقص"). لا تكسر أبداً.
- أنشئ مجلّد agents/ إن لم يوجد، وضع __init__.py فارغاً.
شغّل python -m py_compile على كل ملفّ تبنيه. أرجِع الملفّات + عدد الوكلاء + ملخّص.`,
  { label: `build:grp${i + 1}`, phase: 'Build', schema: BUILD_SCHEMA })))

phase('Integrate')
const INT_SCHEMA = { type: 'object', properties: { engine_file: { type: 'string' }, gene_file: { type: 'string' }, wired: { type: 'boolean' }, total_agents: { type: 'number' }, summary: { type: 'string' } }, required: ['engine_file', 'summary'] }
const integ = await agent(`أنت مهندس تكامل في C:\\Users\\Radhi\\MT5. الوكلاء بُنوا في agents/agent_*.py: ${JSON.stringify(built.filter(Boolean))}.
ابنِ محرّك الإجماع C:\\Users\\Radhi\\MT5\\agent_council.py (windowless daemon، engine_lock.claim، stdout redirect كأسلوب unified_brain.py):
1. يستورد كل AGENTS من كل agents/agent_*.py (اكتشاف تلقائيّ بـ importlib + glob). يطبع العدد الكليّ (يجب ~100).
2. كل دورة (~2ث): لكل عملة من 17 (من market_pulse.json symbols)، يبني ctx (بيانات الفريمات via mt5.copy_rates + حقول smc من النبض)، يُشغّل كل الوكلاء، يجمع الأصوات.
3. الإجماع: verdict = اتجاه الأغلبية الموزونة؛ agreement_pct = نسبة المتّفقين مع الاتجاه الغالب؛ n_voted، votes_buy/sell، top_reasons (أعلى 3 ثقةً).
4. gene = بصمة مستقرّة (hash مرتّب لأسماء الوكلاء المتّفقين مع الاتجاه) — يمثّل «التركيبة».
5. يكتب agent_council.json (ذرّي tmp+os.replace) لكل العملات.
6. 🧬 التعلّم الذاتيّ: يقرأ إغلاقات المنفّذ (magic 20260704) من history؛ حين تربح صفقة، يربط جينها (المحفوظ لحظة الدخول في agent_council_genes.jsonl) ⇒ يزيد ثقة ذلك الجين في gene_registry.json (عدّاد فوز/خسارة + winrate لكل جين). الجينات الرابحة ترفع وزن وكلائها تدريجياً (تعلّم).
${CONTRACT}
ثمّ اربطه بالمنفّذ: عدّل unified_brain.py ليقرأ agent_council.json ويضيف صوت «مجلس الـ100» كعينٍ سادسة موزونة في الصهر (وزن 0.20، أعد توزيع الأوزان). وأضِف agent_council.py و (إن لزم) للحارس watchdog_guard.py (ENGINES + _FOCUS_KEEP) عبر Read+Edit.
شغّل py_compile على كل ما تكتب/تعدّل. لا تُطلق العمليّة. أرجِع engine_file، gene_file، wired، total_agents، ملخّص.`, { label: 'integrate:council', phase: 'Integrate', schema: INT_SCHEMA, effort: 'high' })

phase('Verify')
const V = { type: 'object', properties: { ok: { type: 'boolean' }, agents_loaded: { type: 'number' }, symbols_scored: { type: 'number' }, sample: { type: 'string' }, issues: { type: 'array', items: { type: 'string' } }, summary: { type: 'string' } }, required: ['ok', 'summary'] }
const verify = await agent(`تحقّق نهائيّ في C:\\Users\\Radhi\\MT5 لمحرّك مجلس الـ100 وكيل (${JSON.stringify(integ)}).
1. py_compile على agent_council.py + كل agents/agent_*.py + unified_brain.py — أصلح أي خطأ بنفسك (جراحيّ).
2. شغّل agent_council.py دورةً واحدةً تجريبيّاً (استورد وشغّل دالة الدورة مرّة، أو أطلقه 15ث ثمّ اقرأ agent_council.json). تأكّد: عدد الوكلاء المحمَّلين ~100، وأن ≥15 عملة حصلت على verdict + agreement_pct.
3. أطلقه windowless (subprocess.Popen، engine_lock نسخة واحدة) وتأكّد أنه يكتب agent_council.json طازجاً (<15ث)، وأن unified_brain يقرأ صوت المجلس.
4. اعرض عيّنة: حكم مجلس الـ100 لعملتين (مثلاً الذهب + عملة رابحة) بعدد الأصوات والإجماع.
اضبط ok=true فقط لو: ~100 وكيل محمَّل + ≥15 عملة مُقيَّمة + الملفّ طازج + مربوط. أرجِع صادقاً.`, { label: 'verify:council', phase: 'Verify', schema: V, effort: 'high' })

return { design, built: built.filter(Boolean), integ, verify }
# ربط R-Native بالموظف (2026-10-25)

R-Native ما عاد يرسل أوامر لـ MT5 بنفسه. كل دخول يقرره `friday_v3/algory/r_executor.py`
ينكتب سطر JSON في صندوق الموظف عن طريق `r_native/employee_link.py`:

    C:\Users\Radhi\MT5\employee\data\rnative\signals.jsonl   (أو R_EMPLOYEE_INBOX)

الموظف يقرأ الصندوق بـ `rnative_pb.py`، وكل استراتيجية R تصير playbook للمتدرب باسم `rn_<الاسم>`:

- المتدرب يقيّمها على الورق مثل باقي الـ playbooks.
- الصفقة التجريبية الحقيقية تصير فقط إذا راضي سلّح الـ playbook في `data/trainee/playbook_gate.json`،
  وبعدها تمر عبر البوابة المركزية (مخاطرة الصفقة، daily_dd 5%، حساب تجريبي فقط).
- الإشارات على أسواق غير الذهب تنحفظ وتنعد في `rnative_pb.stats()`؛ المتدرب حالياً يتداول الذهب فقط.

## التركيب على الجهاز (بعد موافقة راضي)
1. انسخ `integrations/employee/rnative_pb.py` إلى `MT5\employee\`.
2. في `trainee.pb()` بعد سطر `repos_pb` أضف:
   ```python
   try:
       import rnative_pb
       out.update(rnative_pb.votes(S, i))
   except Exception:
       pass
   ```
3. شغّل r_executor كالعادة (`python -m friday_v3.algory.r_executor`)؛ PAPER و LIVE كلاهما يرسل للموظف.
   `R_ROUTE=direct_demo` يرجّع الإرسال المباشر القديم للتصحيح فقط.

## الاختبار
    python -m pytest -q tests/test_employee_link.py

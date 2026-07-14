import os
from pathlib import Path
from collections import Counter, defaultdict

def analyze_current_directory():
    root = Path(".")
    
    # جمع البيانات
    all_files = [f for f in root.rglob("*") if f.is_file()]
    all_dirs = [d for d in root.rglob("*") if d.is_dir()]
    
    # أنواع الملفات
    extensions = Counter(f.suffix.lower() for f in all_files)
    
    # تصنيف الملفات حسب المجلد
    folder_stats = defaultdict(int)
    for f in all_files:
        folder = f.parent.name or "ROOT"
        folder_stats[folder] += 1
    
    # التقرير الملخص
    print("=" * 55)
    print("📊 PLUTOBRAIN MT5 — PROJECT ANALYSIS")
    print("=" * 55)
    print(f"\n📁 إجمالي المجلدات:  {len(all_dirs)}")
    print(f"📄 إجمالي الملفات:   {len(all_files)}")
    
    print(f"\n{'─' * 55}")
    print("📌 أنواع الملفات (الأكثر للأقل):")
    print(f"{'─' * 55}")
    
    icons = {
        '.mq5': '🔴 EA', '.mqh': '🟡 Header', '.ex5': '⚫ Compiled',
        '.py': '🐍 Python', '.js': '🟨 JS', '.json': '📋 Config',
        '.md': '📝 Doc', '.txt': '📄 Text', '.csv': '📊 Data',
        '.html': '🌐 Web', '.css': '🎨 Style', '.xml': '📰 XML',
        '.dll': '⚙️ Library', '.set': '⚙️ Settings', '.srv': '🔌 Server',
        '.zip': '📦 Archive', '.png': '🖼️ Image', '.jpg': '🖼️ Image'
    }
    
    for ext, count in extensions.most_common():
        label = icons.get(ext, f"📦 {ext or 'Other'}")
        bar = "█" * min(count, 20)
        print(f"  {label:12} : {count:3} {bar}")
    
    print(f"\n{'─' * 55}")
    print("📂 المجلدات الأكثر ملفات:")
    print(f"{'─' * 55}")
    for folder, count in sorted(folder_stats.items(), key=lambda x: -x[1])[:8]:
        print(f"  └─ {folder:20} : {count} ملف")
    
    if len(folder_stats) > 8:
        print(f"  ... و {len(folder_stats) - 8} مجلدات أخرى")
    
    # حفظ التقرير التفصيلي
    report_path = "mt5_analysis_summary.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"PlutoBrain MT5 Analysis\nPath: {os.getcwd()}\n")
        f.write("=" * 55 + "\n\n")
        f.write(f"Total Folders: {len(all_dirs)}\n")
        f.write(f"Total Files: {len(all_files)}\n\n")
        f.write("File Types:\n")
        for ext, count in extensions.most_common():
            f.write(f"  {ext}: {count}\n")
        f.write("\nFolder Breakdown:\n")
        for folder, count in sorted(folder_stats.items(), key=lambda x: -x[1]):
            f.write(f"  {folder}: {count}\n")
    
    print(f"\n{'=' * 55}")
    print(f"✅ التقرير المحفوظ: {report_path}")
    print("=" * 55)

analyze_current_directory()
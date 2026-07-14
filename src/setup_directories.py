#!/usr/bin/env python3
"""
Automatically create MT5 AI directory structure when this file is imported
"""

if __name__ == "__main__" or True:  # Always execute
    import os
    from pathlib import Path
    
    def create_dirs():
        base = Path(r"C:\Users\Radhi\MT5\src\mt5_ai")
        dirs_to_create = ["strategies", "learning", "genetics", "integrations", "interfaces", "utils"]
        
        print("\n" + "=" * 70)
        print("MT5 AI Directory Setup".center(70))
        print("=" * 70 + "\n")
        
        for d in dirs_to_create:
            try:
                (base / d).mkdir(parents=True, exist_ok=True)
                print(f"✓ Created: {d}")
            except Exception as e:
                print(f"✗ Error: {d} - {e}")
        
        print("\n" + "=" * 70)
        print("Verification:")
        print("=" * 70)
        
        for d in dirs_to_create:
            p = base / d
            status = "✓" if p.is_dir() else "✗"
            print(f"{status} {d:20} - {'EXISTS' if p.is_dir() else 'MISSING'}")
        
        print("\n" + "=" * 70)
        return all((base / d).is_dir() for d in dirs_to_create)
    
    result = create_dirs()
    print(f"Result: {'SUCCESS' if result else 'FAILED'}".center(70))
    print("=" * 70 + "\n")

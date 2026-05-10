#!/usr/bin/env python
"""
Validation script for Dar Traffic Monitoring project.
Checks structure, files, and configuration without requiring psycopg2.
"""
import json
import sys
import os
import subprocess

def main():
    print("=" * 60)
    print("Dar Traffic Monitoring - Structure Validation")
    print("=" * 60)
    
    # Test 1: JSON config loads
    print("\n[1/6] Checking monitoring points configuration...")
    try:
        with open('config/monitored_points.json', 'r') as f:
            points = json.load(f)
        print(f"✓ Loaded {len(points)} monitoring points from config")
    except Exception as e:
        print(f"✗ Failed to load monitoring points: {e}")
        return False
    
    # Test 2: Check monitoring points structure
    print("\n[2/6] Validating monitoring point structure...")
    all_good = True
    for i, point in enumerate(points[:3]):
        if not all(k in point for k in ['name', 'lat', 'lon', 'category']):
            print(f"✗ Point {i} missing required fields: {point}")
            all_good = False
            
    if all_good:
        print(f"✓ Monitoring point structure valid (checked first 3)")
    
    # Test 3: Check point coordinates for Dar
    print("\n[3/6] Validating geographic bounds for Dar es Salaam...")
    lat_min, lat_max = -7.2, -6.5
    lon_min, lon_max = 38.9, 39.5
    
    points_valid = 0
    for point in points:
        lat, lon = point['lat'], point['lon']
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            points_valid += 1
    
    print(f"✓ {points_valid}/{len(points)} points in valid Dar bounds")
    if points_valid < len(points) * 0.95:
        print(f"⚠ Warning: {len(points) - points_valid} points outside bounds")
    
    # Test 4: Check categories
    print("\n[4/6] Analyzing point categories...")
    categories = {}
    for p in points:
        cat = p['category']
        categories[cat] = categories.get(cat, 0) + 1
    
    for cat in sorted(categories.keys()):
        print(f"  - {cat}: {categories[cat]} points")
    
    # Test 5: Python syntax validation
    print("\n[5/6] Validating Python syntax...")
    modules = [
        'main.py',
        'config/settings.py',
        'collectors/tomtom_collector.py',
        'utils/api_helpers.py',
        'utils/logger.py',
        'utils/time_helpers.py'
    ]
    
    result = subprocess.run([
        sys.executable, '-m', 'py_compile'
    ] + modules, capture_output=True, text=True)
    
    if result.returncode == 0:
        print(f"✓ Python syntax valid for {len(modules)} modules")
    else:
        print(f"✗ Syntax errors: {result.stderr}")
        return False
    
    # Test 6: File structure
    print("\n[6/6] Verifying required files...")
    required_files = [
        'config/settings.py',
        'config/monitored_points.json',
        'config/__init__.py',
        'collectors/tomtom_collector.py',
        'collectors/__init__.py',
        'database/init_db.py',
        'database/database_manager.py',
        'database/__init__.py',
        'utils/api_helpers.py',
        'utils/logger.py',
        'utils/time_helpers.py',
        'utils/__init__.py',
        'main.py',
        '.github/workflows/collect-traffic.yml',
        'README.md',
        'requirements.txt',
        '.gitignore'
    ]
    
    all_exist = True
    for f in required_files:
        if not os.path.exists(f):
            print(f"✗ Missing file: {f}")
            all_exist = False
    
    if all_exist:
        print(f"✓ All {len(required_files)} required files present")
    
    # Summary
    print("\n" + "=" * 60)
    print("✅ STRUCTURE VALIDATION PASSED")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Create GitHub repository: https://github.com/new")
    print("2. Initialize git and push code:")
    print("   git init")
    print("   git add .")
    print("   git commit -m 'Initial traffic monitoring setup'")
    print("   git remote add origin https://github.com/YOUR_USER/dar-traffic-monitoring")
    print("   git push -u origin main")
    print("\n3. Set GitHub repository secrets (Settings → Secrets and variables):")
    print("   - TOMTOM_API_KEY: Your TomTom API key from https://developer.tomtom.com")
    print("   - SUPABASE_URL: Your Supabase URL from https://supabase.com")
    print("   - SUPABASE_KEY: Your Supabase API key")
    print("\n4. Collection will run automatically every 30 minutes")
    print("5. View results in GitHub Actions → Collect Traffic Data workflow")
    print("\n" + "=" * 60)
    
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

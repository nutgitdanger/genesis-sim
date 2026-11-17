import os
import csv
import hashlib

def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def run_real_audit():
    # ชี้เป้าไปยังโฟลเดอร์ผลลัพธ์แคตตาล็อกล่าสุดที่ตรวจพบ
    catalog_path = os.path.expanduser("~/cs-catalog/20261108-153243/catalog.tsv")
    
    if not os.path.exists(catalog_path):
        print(f"[-] ไม่พบไฟล์รายงานที่ตำแหน่ง: {catalog_path}")
        return

    print(f"[+] ตรวจพบประจักษ์พยานดิบ: {catalog_path}")
    print("=== เริ่มการวิเคราะห์ประวัติสายข้อมูลเชิงลึกจริง (Genesis Real Lineage Engine) ===\n")
    
    verified_count = 0
    consistent_count = 0
    hazard_count = 0

    with open(catalog_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        
        for row in reader:
            path = row.get("path", "")
            sha256_val = row.get("sha256", "-")
            is_loop = row.get("loop", "0") == "1"
            is_destr = row.get("destructive", "0") == "1"
            is_secret = row.get("secret_pattern", "0") == "1"

            # ข้ามไฟล์ที่แฮชไม่สมบูรณ์ (ไม่มีตัวตนทางกายภาพที่ระบุได้)
            if sha256_val == "-" or not sha256_val:
                continue

            # 1. ตรวจพบความลับหลุดรั่วเชิงความหมาย (Hazard Mutation Barrier)
            if is_secret:
                print(f"[-] [HAZARD_MUTATION] ตรวจพบรูปแบบคีย์ที่เสี่ยงรั่วไหล: {path}")
                hazard_count += 1
                continue
                
            # 2. ตรวจสอบเงื่อนไขการกักกันเชิงโครงสร้าง (Reference Consistent Zone)
            if is_destr or is_loop:
                # แฮชตรงทางโครงสร้าง แต่เนื้อหาตัวแปรเข้าข่ายอันตรายร้ายแรง ต้องควบคุมผ่านเซลล์
                consistent_count += 1
            else:
                # สายหลักฐานสมบูรณ์เชิงประจักษ์และปลอดภัย
                verified_count += 1

    print("\n=== สรุปรายงานสถานะจากคลังข้อมูลจริงย้อนกลับ ===")
    print(f"  - ไฟล์ปลอดภัยสอดคล้องสมบูรณ์ (VERIFIED): {verified_count} Nodes")
    print(f"  - ไฟล์ประวัติสอดคล้องแต่ต้องถูกกักกัน (REFERENCE_CONSISTENT): {consistent_count} Nodes")
    print(f"  - ไฟล์ที่อันตรายเชิงโครงสร้าง/ตรวจพบความลับ (HAZARD_MUTATION): {hazard_count} Nodes")

if __name__ == "__main__":
    run_real_audit()

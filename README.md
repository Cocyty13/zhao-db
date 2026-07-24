# Zhao Roleplay Database

`zhao-roleplay.db` เป็นแหล่งข้อมูลหลัก (source of truth) สำหรับข้อมูลเนื้อเรื่องทั้งหมด
ทั้งการอ่าน ค้นหา และอัปเดต ส่วนไฟล์ XLSX เป็นไฟล์ส่งออกสำหรับเปิดดูหรือสำรองข้อมูลเท่านั้น

ไฟล์สำคัญ:

- `zhao-roleplay.db` — ฐานข้อมูลหลัก
- `zhao-roleplay-database.xlsx` — snapshot เก่าสำหรับอ้างอิง/ย้ายข้อมูล ไม่ต้องอัปเดตในงานประจำ
- `tools/db_admin.py` — ค้นหา เพิ่ม แก้ไข สร้างดัชนีใหม่ และตรวจฐานข้อมูล
- `tools/build_db.py` — เครื่องมือนำเข้า XLSX แบบเดิม ใช้เฉพาะการย้ายข้อมูล

## โครงสร้าง SQLite

ข้อมูลเดิมทุกหมวดถูกเก็บเป็นตารางครบถ้วน:

`Characters`, `Locations`, `Scenes`, `Events`, `Relationships`,
`Facts_Memory`, `Plot_Threads`, `Inventory`, `Location_Tracker`,
`Travel_Times`, `World_Rules`, `Military_Scale`, `Naming_Kinship`
และ `Planned_Arcs`

ตารางช่วย:

- `_meta` — รุ่นฐานข้อมูลและสถานะ `canonical_source=sqlite`
- `_sheets` — รายชื่อแท็บ จำนวนแถว และจำนวนคอลัมน์
- `_columns` — การจับคู่หัวคอลัมน์เดิมกับชื่อคอลัมน์ใน SQLite
- `search_index` — ดัชนีค้นหาข้ามทุกตารางด้วย FTS5

ทุกตารางมี `_row_number` เพื่ออ้างกลับไปยังเลขแถวเดิมใน Excel และหัวคอลัมน์
ที่ซ้ำจะเติม `__2`, `__3` โดยไม่ทำให้ข้อมูลเดิมสูญหาย

Trigger ของแต่ละตารางจะปรับ `search_index` และจำนวนแถวใน `_sheets`
อัตโนมัติเมื่อเพิ่ม แก้ไข หรือลบข้อมูลผ่าน SQLite โดยตรง

## ตัวอย่างใช้งาน

```sql
SELECT * FROM Characters WHERE ID = 'CH-001';

SELECT * FROM Events
WHERE Canon_Status = 'CANON'
ORDER BY _row_number;

SELECT sheet_name, row_number, record_id, content
FROM search_index
WHERE search_index MATCH 'หลี่หรง';
```

ค้นหาผ่าน CLI:

```bash
python3 tools/db_admin.py search หลี่หรง
```

แก้ไขรายการด้วย ID:

```bash
python3 tools/db_admin.py update Characters \
  --id CH-001 \
  --set '{"Current_Location":"จ้าวจิง/จวนองค์ชายรอง"}'
```

ถ้า ID ซ้ำ ให้ระบุ `_row_number` โดยตรง:

```bash
python3 tools/db_admin.py update Relationships \
  --row 19 \
  --set '{"Current_State":"ข้อความใหม่"}'
```

เพิ่มรายการ:

```bash
python3 tools/db_admin.py insert Locations \
  --data '{"ID":"LOC-012","Name":"สถานที่ใหม่","Canon_Status":"CANON"}'
```

## ตรวจฐานข้อมูล

```bash
python3 tools/db_admin.py validate
```

การตรวจครอบคลุม `PRAGMA integrity_check` โครงสร้างตาราง คอลัมน์ และจำนวนรายการ
ใน `search_index` ของทุกหมวด

สร้างไฟล์สรุปเมื่อจำเป็น:

```bash
python3 tools/db_admin.py summary \
  --output zhao-roleplay-db-summary.json
```

## นำเข้าจาก XLSX แบบเดิม

`tools/build_db.py` ยังคงอยู่สำหรับการย้ายข้อมูลจากไฟล์เก่าเท่านั้น
ไม่ควรใช้สร้างทับ `zhao-roleplay.db` ในงานประจำ เพราะ SQLite เป็นแหล่งข้อมูลหลักแล้ว
สคริปต์จะปฏิเสธการเขียนทับฐานหลักโดยอัตโนมัติ เว้นแต่ระบุ `--force-import`
อย่างชัดเจน

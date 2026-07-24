# Zhao Roleplay Database

ฐานข้อมูลเนื้อเรื่องมีสองรูปแบบ:

- `zhao-roleplay-database.xlsx` — ไฟล์ต้นฉบับสำหรับเปิดดูและแก้ไขด้วย Excel
- `zhao-roleplay.db` — SQLite สำหรับอ่าน ค้นหา และอัปเดตด้วยโปรแกรมอย่างรวดเร็ว

## โครงสร้าง SQLite

ทุกแท็บใน Excel ถูกเก็บเป็นตารางชื่อเดียวกันครบถ้วน:

`Characters`, `Locations`, `Scenes`, `Events`, `Relationships`,
`Facts_Memory`, `Plot_Threads`, `Inventory`, `Location_Tracker`,
`Travel_Times`, `World_Rules`, `Military_Scale`, `Naming_Kinship`
และ `Planned_Arcs`

ตารางช่วย:

- `_meta` — รุ่นฐานข้อมูล แหล่งข้อมูล และเวลาสร้าง
- `_sheets` — รายชื่อแท็บ จำนวนแถว และจำนวนคอลัมน์
- `_columns` — การจับคู่หัวคอลัมน์เดิมกับชื่อคอลัมน์ใน SQLite
- `search_index` — ดัชนีค้นหาข้ามทุกตารางด้วย FTS5

ทุกตารางมี `_row_number` เพื่ออ้างกลับไปยังเลขแถวเดิมใน Excel และหัวคอลัมน์
ที่ซ้ำจะเติม `__2`, `__3` โดยไม่ทำให้ข้อมูลเดิมสูญหาย

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

## สร้างฐานใหม่จาก Excel

```bash
python3 tools/build_db.py \
  zhao-roleplay-database.xlsx \
  zhao-roleplay.db \
  --summary zhao-roleplay-db-summary.json
```

สคริปต์จะสร้างฐานใหม่ทั้งหมด ตรวจ `PRAGMA integrity_check` และเขียนสรุป
จำนวนแถวของทุกแท็บเพื่อใช้ตรวจเทียบกับต้นฉบับ

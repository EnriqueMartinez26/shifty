import re

file_path = "tests/integration/test_appointments_api.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace("from datetime import datetime, timedelta\n", "from datetime import datetime, timedelta, timezone\n")
content = content.replace("datetime.utcnow()", "datetime.now(timezone.utc)")

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

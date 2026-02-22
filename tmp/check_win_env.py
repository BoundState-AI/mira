import sys
print('python', sys.version)
mods=['psycopg2','pydantic','httpx','fastapi']
for m in mods:
    try:
        __import__(m)
        print(m,'ok')
    except Exception as e:
        print(m,'err',type(e).__name__,str(e))

from fastapi import FastAPI

app = FastAPI()

@app.get('/')
def read_root():
    return {'msg': 'Skill Snapshot API is live'}

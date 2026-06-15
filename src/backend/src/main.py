from fastapi import FastAPI
# Initialize the FastAPI application
app = FastAPI()

# Define a basic GET route
@app.get("/")
def read_root():
    return {"message": "Welcome to my FastAPI app!"}


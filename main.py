import re
import logging
import uuid
from datetime import datetime, timedelta

import uvicorn
from fastapi import FastAPI, Depends, HTTPException, status, APIRouter, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse

import crud
import models
import schemas
from database import SessionLocal, engine

models.Base.metadata.create_all(bind=engine)

# route path
app = FastAPI(root_path="/api/")
router = APIRouter()

# Need to password hash
SECRET_KEY = "d01e3f9110d397d00cb5ffc2cd498180a16c3999191a032ef404424daec9ada4"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# CORS setting
origins = [
    "http://localhost",
    "http://localhost:3001",
    "http://localhost:8000",
    "http://qq0201.iptime.org"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = logging.getLogger(__name__)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    exc_str = f'{exc}'.replace('\n', ' ').replace('   ', ' ')
    # or logger.error(f'{exc}')
    logger.error(request, exc_str)
    content = {'status_code': 10422, 'message': exc_str, 'data': None}
    return JSONResponse(content=content, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def authenticate_user(db, id: str, password: str):
    if re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", id):
        user = crud.get_user_by_email(db, id)
    else:
        user = crud.get_user_by_name(db, id)

    if not user:
        return None
    if password != user.PW:
        return None

    return user


def create_access_token(data: dict, expires_delta=None):
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

    return encoded_jwt


@app.post("/login", response_model=schemas.Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.Email}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "Bearer"}


@app.get("/users/me/", response_model=schemas.User)
def get_current_user(db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=ALGORITHM)
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = schemas.TokenData(username=username)
    except JWTError as e:
        raise credentials_exception

    user = crud.get_user_by_email(db, email=token_data.username)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"User not found {token_data}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


@app.post("/register", response_model=schemas.User)
async def register_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    db_user = crud.get_user_by_email(db, email=user.Email)
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    user.UUID = uuid.uuid4()
    return crud.create_user(db=db, user=user)


@app.post("/database/create", response_model=schemas.CalendarDatabaseCreate)
async def create_database(database: schemas.CalendarDatabaseCreate, db: Session = Depends(get_db),
                          current_user: schemas.User = Depends(get_current_user)):
    database.UUID = uuid.uuid4()
    database.DatabaseName = database.DatabaseName.replace(' ', '_')
    database.Owner = current_user.UUID
    return crud.create_database(db=db, database=database)


@app.get("/database")
async def get_databases(db: Session = Depends(get_db), current_user: schemas.User = Depends(get_current_user)):
    return crud.get_databases(db=db, owner_id=current_user.UUID)


@app.post("/schedule/create", response_model=schemas.Schedule)
async def create_schedule(schedule: schemas.ScheduleCreate, db: Session = Depends(get_db),
                          current_user: schemas.User = Depends(get_current_user)):
    schedule.UUID = uuid.uuid4()
    schedule.Owner = current_user.UUID
    return crud.create_schedule(db=db, schedule=schedule)


@app.post("/schedule/delete")
async def delete_schedule(rq: Request, db: Session = Depends(get_db)):
    rq_body = await rq.json()
    schedule_id = rq_body.get("UUID")
    return crud.delete_schedule(db=db, schedule_id=schedule_id)


@app.get("/schedule")
async def get_schedules(db: Session = Depends(get_db), current_user: schemas.User = Depends(get_current_user)):
    return crud.get_schedules(db=db, user_id=current_user.UUID)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

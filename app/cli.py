import argparse
import getpass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import User
from app.schemas import UserCreate
from app.security import passwords


def main():
    parser = argparse.ArgumentParser(description="Create CRM admin (interactive password)")
    parser.add_argument("command", choices=["create-admin"])
    parser.add_argument("--username", default="admin")
    parser.add_argument("--name", default="Administrator")
    args = parser.parse_args()
    password = getpass.getpass("Parol (kamida 12 belgi): ")
    if password != getpass.getpass("Parolni qaytaring: "):
        raise SystemExit("Parollar mos emas")
    data = UserCreate(username=args.username, full_name=args.name, password=password, role="admin")
    with Session(get_engine()) as db, db.begin():
        if db.scalar(select(User.id).where(User.username == data.username)):
            raise SystemExit("Login band")
        db.add(
            User(
                username=data.username,
                full_name=data.full_name,
                role="admin",
                password_hash=passwords.hash(data.password),
            )
        )
    print("Admin yaratildi")


if __name__ == "__main__":
    main()

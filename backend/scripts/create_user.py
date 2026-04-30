"""Create or update an admin user. Run on the server, never store the password in chat or git.

Usage:
    python -m scripts.create_user
"""
import getpass
import sys

from app.database import Base, SessionLocal, engine
from app.models import User
from app.security import hash_password


def main() -> None:
    Base.metadata.create_all(bind=engine)
    username = input("Username: ").strip()
    if not username:
        print("Username required")
        sys.exit(1)
    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm: ")
    if password != confirm or not password:
        print("Passwords did not match")
        sys.exit(1)

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if user:
            user.password_hash = hash_password(password)
            print(f"Updated password for {username}")
        else:
            db.add(User(username=username, password_hash=hash_password(password)))
            print(f"Created user {username}")
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()

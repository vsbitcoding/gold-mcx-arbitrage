"""Create or update a dashboard user. Run on the server; the password never
touches git or chat logs when run interactively.

Usage:
    python -m scripts.create_user                       # interactive, role=admin
    python -m scripts.create_user <name> <role>         # interactive password
    python -m scripts.create_user <name> <role> <pass>  # non-interactive

Roles: admin (whole dashboard) | trader (Auto Trades page only).
"""
import getpass
import sys

from app.database import Base, SessionLocal, engine
from app.models import User
from app.security import hash_password

ROLES = ("admin", "trader")


def main() -> None:
    Base.metadata.create_all(bind=engine)
    args = sys.argv[1:]
    username = (args[0] if args else input("Username: ")).strip()
    if not username:
        print("Username required")
        sys.exit(1)
    role = (args[1] if len(args) > 1 else "admin").strip().lower()
    if role not in ROLES:
        print(f"Role must be one of {ROLES}")
        sys.exit(1)
    if len(args) > 2:
        password = args[2]
    else:
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Confirm: "):
            print("Passwords did not match")
            sys.exit(1)
    if not password:
        print("Password required")
        sys.exit(1)

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if user:
            user.password_hash = hash_password(password)
            user.role = role
            print(f"Updated {username} (role={role})")
        else:
            db.add(User(username=username, password_hash=hash_password(password), role=role))
            print(f"Created {username} (role={role})")
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()

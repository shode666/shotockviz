"""Script to create an initial user account."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main():
    from core.database import AsyncSessionLocal, create_tables
    from core.security import hash_password
    from models.user import User, UserRole
    from sqlalchemy import select

    await create_tables()

    email = input("Email: ").strip()
    password = input("Password: ").strip()
    display_name = input("Display name: ").strip()
    is_admin = input("Admin? (y/N): ").strip().lower() == "y"

    async with AsyncSessionLocal() as db:
        existing = await db.execute(select(User).where(User.email == email))
        if existing.scalar_one_or_none():
            print(f"Error: User {email} already exists.")
            return

        user = User(
            email=email,
            password_hash=hash_password(password),
            display_name=display_name,
            role=UserRole.admin if is_admin else UserRole.user,
        )
        db.add(user)
        await db.commit()
        print(f"✅ User created: {email} (role: {user.role.value})")


if __name__ == "__main__":
    asyncio.run(main())

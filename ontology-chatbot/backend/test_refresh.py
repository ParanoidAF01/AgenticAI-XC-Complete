import asyncio
import uuid
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.core.config import get_settings
from app.db.repositories.token_repository import create_refresh_token, get_refresh_token
from app.db.repositories.user_repository import create_user

async def main():
    settings = get_settings()
    engine = create_async_engine(settings.POSTGRES_URL)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    
    async with session_factory() as db:
        # Create a dummy user
        test_email = f"test_{uuid.uuid4()}@example.com"
        user = await create_user(
            db, 
            email=test_email, 
            password_hash="hash", 
            display_name="Test"
        )
        
        # Create a refresh token
        raw_token = "my_secret_raw_token_123"
        rt = await create_refresh_token(db, user_id=user.id, raw_token=raw_token)
        await db.commit()
        
    async with session_factory() as db:
        # Retrieve it
        record = await get_refresh_token(db, "my_secret_raw_token_123")
        if record:
            print("SUCCESS! Token found.")
        else:
            print("FAILURE! Token not found.")
            
if __name__ == "__main__":
    asyncio.run(main())
